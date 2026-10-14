"""LLM_PROVIDER selects the one provider (ollama, groq or gemini) every LLM
call uses. There is no fallback between providers and no token cap."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.classes.ollama_connector import (
    LLMUnavailableError,
    OllamaConnector,
    llm_config_errors,
    llm_provider,
)


def _ollama_chunk(content):
    chunk = MagicMock()
    chunk.message.content = content
    return chunk


def _ollama_client(tokens=None, reply=None, raises=None, fail_after=None):
    client = MagicMock()
    if raises is not None:
        client.chat = AsyncMock(side_effect=raises)
        return client
    if tokens is not None:
        async def _gen():
            for i, token in enumerate(tokens):
                if fail_after is not None and i == fail_after:
                    raise ConnectionError("ollama dropped the connection")
                yield _ollama_chunk(token)
        client.chat = AsyncMock(return_value=_gen())
    else:
        response = MagicMock()
        response.message.content = reply
        client.chat = AsyncMock(return_value=response)
    return client


def _groq_client(tokens=None, reply=None, raises=None):
    client = MagicMock()
    if raises is not None:
        client.chat.completions.create = AsyncMock(side_effect=raises)
    elif tokens is not None:
        async def _gen():
            for token in tokens:
                chunk = MagicMock()
                chunk.choices = [MagicMock()]
                chunk.choices[0].delta.content = token
                yield chunk
        client.chat.completions.create = AsyncMock(return_value=_gen())
    else:
        choice = MagicMock()
        choice.message.content = reply
        completion = MagicMock()
        completion.choices = [choice]
        client.chat.completions.create = AsyncMock(return_value=completion)
    return client


def _gemini(text=None, raises=None):
    gemini = MagicMock()
    if raises is not None:
        gemini.aio.models.generate_content = AsyncMock(side_effect=raises)
    else:
        response = MagicMock()
        response.text = text
        gemini.aio.models.generate_content = AsyncMock(return_value=response)
    return gemini


async def _collect(agen):
    return [chunk async for chunk in agen]


def _text(chunks):
    return "".join(c for c in chunks if isinstance(c, str))


@pytest.fixture
def all_providers():
    """Mocks for all three providers, so a test can assert only one was used."""
    ollama = _ollama_client(tokens=["Ollama ", "answer."])
    groq = _groq_client(tokens=["Groq ", "answer."])
    gemini = _gemini(text="Gemini answer.")
    with patch.object(OllamaConnector, "_get_async_ollama", return_value=ollama), \
         patch.object(OllamaConnector, "_get_async_groq", return_value=groq), \
         patch.object(OllamaConnector, "gemini", gemini):
        yield ollama, groq, gemini


class TestProviderSelection:
    def test_defaults_to_ollama(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        assert llm_provider() == "ollama"

    def test_value_is_normalized(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "  Gemini ")
        assert llm_provider() == "gemini"

    def test_unknown_provider_is_a_config_error(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        assert "not one of" in llm_config_errors()[0]

    @pytest.mark.parametrize("provider,missing", [
        ("ollama", "OLLAMA_GEN_MODEL"),
        ("groq", "GROQ_API_KEY"),
        ("groq", "GROQ_MODEL_NAME"),
        ("gemini", "GEMINI_API_KEY"),
    ])
    def test_missing_required_setting_is_reported(self, monkeypatch, provider, missing):
        monkeypatch.setenv("LLM_PROVIDER", provider)
        for var in ("OLLAMA_GEN_MODEL", "GROQ_API_KEY", "GROQ_MODEL_NAME", "GEMINI_API_KEY"):
            monkeypatch.setenv(var, "set")
        monkeypatch.setenv(missing, "")
        assert any(missing in error for error in llm_config_errors())

    def test_complete_configuration_has_no_errors(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.setenv("OLLAMA_GEN_MODEL", "llama3.1:8b")
        assert llm_config_errors() == []

    def test_backend_refuses_to_start_with_incomplete_llm_config(self):
        import importlib
        import src.main

        with patch.dict("os.environ", {"LLM_PROVIDER": "ollama", "OLLAMA_GEN_MODEL": ""}), \
             patch("dotenv.load_dotenv"):
            with pytest.raises(RuntimeError, match="OLLAMA_GEN_MODEL"):
                importlib.reload(src.main)

        importlib.reload(src.main)


class TestStreamingUsesOnlyTheChosenProvider:
    @pytest.mark.asyncio
    async def test_ollama(self, monkeypatch, all_providers):
        ollama, groq, gemini = all_providers
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.setenv("OLLAMA_GEN_MODEL", "llama3.1:8b")
        chunks = await _collect(OllamaConnector._stream_completion("prompt"))
        assert _text(chunks) == "Ollama answer."
        assert chunks[-1] == {"_model": "llama3.1:8b"}
        assert "options" not in ollama.chat.call_args.kwargs
        groq.chat.completions.create.assert_not_called()
        gemini.aio.models.generate_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_groq(self, monkeypatch, all_providers):
        ollama, groq, gemini = all_providers
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        chunks = await _collect(OllamaConnector._stream_completion("prompt"))
        assert _text(chunks) == "Groq answer."
        assert "max_tokens" not in groq.chat.completions.create.call_args.kwargs
        ollama.chat.assert_not_called()
        gemini.aio.models.generate_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_gemini(self, monkeypatch, all_providers):
        ollama, groq, gemini = all_providers
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        monkeypatch.setenv("GEMINI_MODEL_NAME", "gemini-2.5-pro")
        chunks = await _collect(OllamaConnector._stream_completion("prompt"))
        assert _text(chunks) == "Gemini answer."
        assert chunks[-1] == {"_model": "gemini-2.5-pro"}
        assert "config" not in gemini.aio.models.generate_content.call_args.kwargs
        ollama.chat.assert_not_called()
        groq.chat.completions.create.assert_not_called()


class TestStreamingFailures:
    @pytest.mark.asyncio
    async def test_failure_before_any_text_raises_without_trying_another_provider(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        groq = _groq_client(raises=RuntimeError("rate limit exceeded"))
        gemini = _gemini(text="should never be used")
        with patch.object(OllamaConnector, "_get_async_groq", return_value=groq), \
             patch.object(OllamaConnector, "gemini", gemini):
            with pytest.raises(LLMUnavailableError, match="rate limit exceeded"):
                await _collect(OllamaConnector._stream_completion("prompt"))
        gemini.aio.models.generate_content.assert_not_called()

    def test_unavailable_error_is_a_value_error(self):
        # The routers turn ValueError from generation into a 503.
        assert issubclass(LLMUnavailableError, ValueError)

    @pytest.mark.asyncio
    async def test_failure_mid_answer_keeps_the_partial_text(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.setenv("OLLAMA_GEN_MODEL", "llama3.1:8b")
        ollama = _ollama_client(tokens=["Partial ", "more"], fail_after=1)
        with patch.object(OllamaConnector, "_get_async_ollama", return_value=ollama):
            chunks = await _collect(OllamaConnector._stream_completion("prompt"))
        assert _text(chunks) == "Partial "


class TestCompleteUsesOnlyTheChosenProvider:
    @pytest.mark.asyncio
    async def test_ollama(self, monkeypatch, all_providers):
        ollama, groq, _ = all_providers
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.setenv("OLLAMA_GEN_MODEL", "llama3.1:8b")
        ollama.chat = AsyncMock(return_value=MagicMock(message=MagicMock(content="  Local reply ")))
        assert await OllamaConnector.complete("prompt", label="test") == "Local reply"
        assert "options" not in ollama.chat.call_args.kwargs
        groq.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_groq_uses_low_reasoning_and_no_token_cap(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        groq = _groq_client(reply="Groq reply")
        with patch.object(OllamaConnector, "_get_async_groq", return_value=groq):
            assert await OllamaConnector.complete("prompt", label="test") == "Groq reply"
        kwargs = groq.chat.completions.create.call_args.kwargs
        assert kwargs["reasoning_effort"] == "low"
        assert "max_tokens" not in kwargs

    @pytest.mark.asyncio
    async def test_gemini(self, monkeypatch, all_providers):
        _, groq, gemini = all_providers
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        gemini.aio.models.generate_content = AsyncMock(return_value=MagicMock(text="Gemini reply"))
        assert await OllamaConnector.complete("prompt", label="test") == "Gemini reply"
        groq.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_provider_error_returns_none_without_trying_another(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        groq = _groq_client(raises=RuntimeError("down"))
        gemini = _gemini(text="should never be used")
        with patch.object(OllamaConnector, "_get_async_groq", return_value=groq), \
             patch.object(OllamaConnector, "gemini", gemini):
            assert await OllamaConnector.complete("prompt", label="test") is None
        gemini.aio.models.generate_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_reply_returns_none(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        groq = _groq_client(reply="   ")
        with patch.object(OllamaConnector, "_get_async_groq", return_value=groq):
            assert await OllamaConnector.complete("prompt", label="test") is None


class TestUrlClassification:
    @pytest.mark.asyncio
    async def test_uses_the_configured_provider_without_a_token_cap(self):
        from src.jobs.url_classification import _classify
        with patch.object(OllamaConnector, "complete", AsyncMock(return_value="Yes")) as complete:
            assert await _classify("Glioblastoma treatment outcomes") == (True, "yes")
        assert "max_tokens" not in complete.call_args.kwargs

    @pytest.mark.asyncio
    async def test_no_answer_raises_instead_of_rejecting(self):
        from src.jobs.url_classification import _classify
        with patch.object(OllamaConnector, "complete", AsyncMock(return_value=None)):
            with pytest.raises(RuntimeError):
                await _classify("Some page")
