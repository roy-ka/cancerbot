import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import groq

from src.classes.ollama_connector import OllamaConnector

CONTEXT = [{"id": "src-001", "content_for_embedding": "Cancer cells exhibit the Warburg effect."}]


def _make_gemini_response(content):
    response = MagicMock()
    response.text = content
    return response


def _gemini_mock(content=None, raises=None):
    m = MagicMock()
    if raises is not None:
        m.models.generate_content.side_effect = raises
    else:
        m.models.generate_content.return_value = _make_gemini_response(content)
    return m


def _make_groq_stream(tokens):
    async def _stream():
        for token in tokens:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = token
            yield chunk
    return _stream()


def _async_groq_mock(tokens=None, raises=None):
    """Mock for `AsyncGroq(...)` — patch target is groq.AsyncGroq itself, since
    stream_text does `from groq import AsyncGroq` locally at call time."""
    instance = MagicMock()
    if raises is not None:
        instance.chat.completions.create = AsyncMock(side_effect=raises)
    else:
        instance.chat.completions.create = AsyncMock(return_value=_make_groq_stream(tokens or []))
    factory = MagicMock(return_value=instance)
    return factory, instance


def _rate_limit_exc():
    return groq.RateLimitError(
        "Rate limit exceeded",
        response=MagicMock(status_code=429, headers={}),
        body={},
    )


def _server_error_exc():
    return groq.InternalServerError(
        "Internal server error",
        response=MagicMock(status_code=500, headers={}),
        body={},
    )


async def _collect(agen):
    chunks = []
    async for chunk in agen:
        chunks.append(chunk)
    return chunks


def _make_groq_completion(content):
    choice = MagicMock()
    choice.message.content = content
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _async_groq_completion_mock(content=None, raises=None):
    """Mock for the non-streaming AsyncGroq call generate_title makes."""
    instance = MagicMock()
    if raises is not None:
        instance.chat.completions.create = AsyncMock(side_effect=raises)
    else:
        instance.chat.completions.create = AsyncMock(return_value=_make_groq_completion(content))
    factory = MagicMock(return_value=instance)
    return factory, instance


class TestGroqGeminiFallback:
    """Tests for stream_text's Groq -> Gemini fallback (the actual production
    generation path used by conversations.py; the old blocking generate_text
    method has been removed since streaming replaced it)."""

    @pytest.mark.asyncio
    async def test_groq_success_streams_tokens(self):
        factory, instance = _async_groq_mock(tokens=["Warburg ", "effect ", "answer."])
        with patch("groq.AsyncGroq", factory):
            chunks = await _collect(OllamaConnector.stream_text(CONTEXT, "What is the Warburg effect?", []))
        text_chunks = [c for c in chunks if isinstance(c, str)]
        sentinel = [c for c in chunks if isinstance(c, dict)]
        assert "".join(text_chunks) == "Warburg effect answer."
        assert len(sentinel) == 1
        instance.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_groq_rate_limit_falls_back_to_gemini(self):
        factory, _ = _async_groq_mock(raises=_rate_limit_exc())
        mock_gemini = _gemini_mock(content="Gemini fallback answer.")
        with patch("groq.AsyncGroq", factory), \
             patch.object(OllamaConnector, "gemini", mock_gemini):
            chunks = await _collect(OllamaConnector.stream_text(CONTEXT, "What is cancer?", []))
        text_chunks = [c for c in chunks if isinstance(c, str)]
        assert "Gemini fallback answer" in "".join(text_chunks)
        mock_gemini.models.generate_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_groq_server_error_falls_back_to_gemini(self):
        factory, _ = _async_groq_mock(raises=_server_error_exc())
        mock_gemini = _gemini_mock(content="Gemini server fallback.")
        with patch("groq.AsyncGroq", factory), \
             patch.object(OllamaConnector, "gemini", mock_gemini):
            chunks = await _collect(OllamaConnector.stream_text(CONTEXT, "What is cancer?", []))
        text_chunks = [c for c in chunks if isinstance(c, str)]
        assert "Gemini server fallback" in "".join(text_chunks)

    @pytest.mark.asyncio
    async def test_gemini_not_called_on_groq_success(self):
        factory, _ = _async_groq_mock(tokens=["Groq answer."])
        mock_gemini = _gemini_mock()
        with patch("groq.AsyncGroq", factory), \
             patch.object(OllamaConnector, "gemini", mock_gemini):
            await _collect(OllamaConnector.stream_text(CONTEXT, "What is cancer?", []))
        mock_gemini.models.generate_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_both_providers_fail_raises_value_error(self):
        factory, _ = _async_groq_mock(raises=_rate_limit_exc())
        mock_gemini = _gemini_mock(raises=Exception("Gemini unavailable"))
        with patch("groq.AsyncGroq", factory), \
             patch.object(OllamaConnector, "gemini", mock_gemini), \
             pytest.raises(ValueError, match="AI generation unavailable"):
            await _collect(OllamaConnector.stream_text(CONTEXT, "What is cancer?", []))

    @pytest.mark.asyncio
    async def test_alias_to_id_sentinel_correct_on_fallback_path(self):
        """stream_text yields raw [sourceN] aliases (the caller runs _post_process
        on the assembled text); it must still yield a correct alias_to_id sentinel
        for the caller to substitute stable source IDs afterward."""
        factory, _ = _async_groq_mock(raises=_rate_limit_exc())
        mock_gemini = _gemini_mock(content="Cancer uses glucose [source1].")
        with patch("groq.AsyncGroq", factory), \
             patch.object(OllamaConnector, "gemini", mock_gemini):
            chunks = await _collect(OllamaConnector.stream_text(CONTEXT, "What is cancer?", []))
        text_chunks = [c for c in chunks if isinstance(c, str)]
        assert "[source1]" in "".join(text_chunks)
        sentinel = next(c for c in chunks if isinstance(c, dict))
        assert sentinel.get("source1") == "src-001"


class TestGenerateTitle:
    @pytest.mark.asyncio
    async def test_uses_groq_generated_title(self):
        factory, instance = _async_groq_completion_mock(content="Mebendazole for Glioblastoma")
        with patch("groq.AsyncGroq", factory):
            title = await OllamaConnector.generate_title("can Mebendazole help against GBM?")
        assert title == "Mebendazole for Glioblastoma"
        instance.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_strips_quotes_and_trailing_period(self):
        factory, _ = _async_groq_completion_mock(content='"Mebendazole for Glioblastoma."')
        with patch("groq.AsyncGroq", factory):
            title = await OllamaConnector.generate_title("can Mebendazole help against GBM?")
        assert title == "Mebendazole for Glioblastoma"

    @pytest.mark.asyncio
    async def test_falls_back_to_heuristic_on_groq_error(self):
        factory, _ = _async_groq_completion_mock(raises=_rate_limit_exc())
        with patch("groq.AsyncGroq", factory):
            title = await OllamaConnector.generate_title("can Mebendazole help against GBM?")
        assert title == "Can Mebendazole help against GBM"

    @pytest.mark.asyncio
    async def test_falls_back_to_heuristic_on_unexpected_error(self):
        factory, _ = _async_groq_completion_mock(raises=RuntimeError("boom"))
        with patch("groq.AsyncGroq", factory):
            title = await OllamaConnector.generate_title("tell me about cancer")
        assert title == "Tell me about cancer"

    @pytest.mark.asyncio
    async def test_empty_text_returns_placeholder_without_calling_groq(self):
        factory, instance = _async_groq_completion_mock(content="should not be used")
        with patch("groq.AsyncGroq", factory):
            title = await OllamaConnector.generate_title("   ")
        assert title == "New Conversation"
        instance.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_groq_choices_falls_back(self):
        completion = MagicMock()
        completion.choices = []
        instance = MagicMock()
        instance.chat.completions.create = AsyncMock(return_value=completion)
        factory = MagicMock(return_value=instance)
        with patch("groq.AsyncGroq", factory):
            title = await OllamaConnector.generate_title("what is apoptosis?")
        assert title == "What is apoptosis"
