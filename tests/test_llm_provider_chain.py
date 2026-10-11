"""Provider chain for every LLM call: local Ollama (only when
OLLAMA_GEN_MODEL is set), then Groq, then Gemini."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.classes.ollama_connector as connector_module
from src.classes.ollama_connector import OllamaConnector

OLLAMA_MODEL = "llama3.1:8b"


def _ollama_chunk(content, done=False, done_reason=None):
    chunk = MagicMock()
    chunk.message.content = content
    chunk.done = done
    chunk.done_reason = done_reason
    return chunk


def _ollama_stream(tokens, done_reason="stop", fail_after=None, delay=0.0):
    async def _gen():
        if delay:
            await asyncio.sleep(delay)
        for i, token in enumerate(tokens):
            if fail_after is not None and i == fail_after:
                raise ConnectionError("ollama dropped the connection")
            last = i == len(tokens) - 1
            yield _ollama_chunk(token, done=last, done_reason=done_reason if last else None)
    return _gen()


def _ollama_client(stream=None, reply=None, raises=None):
    client = MagicMock()
    if raises is not None:
        client.chat = AsyncMock(side_effect=raises)
    elif stream is not None:
        client.chat = AsyncMock(return_value=stream)
    else:
        response = MagicMock()
        response.message.content = reply
        client.chat = AsyncMock(return_value=response)
    return client


def _groq_stream(tokens):
    async def _gen():
        for i, token in enumerate(tokens):
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = token
            chunk.choices[0].finish_reason = "stop" if i == len(tokens) - 1 else None
            yield chunk
    return _gen()


def _groq_client(stream_tokens=None, reply=None, raises=None):
    client = MagicMock()
    if raises is not None:
        client.chat.completions.create = AsyncMock(side_effect=raises)
    elif stream_tokens is not None:
        client.chat.completions.create = AsyncMock(return_value=_groq_stream(stream_tokens))
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
        response.candidates = []
        gemini.aio.models.generate_content = AsyncMock(return_value=response)
    return gemini


async def _collect(agen):
    return [chunk async for chunk in agen]


def _text(chunks):
    return "".join(c for c in chunks if isinstance(c, str))


def _sentinel(chunks):
    return next(c for c in chunks if isinstance(c, dict))


@pytest.fixture
def ollama_enabled(monkeypatch):
    monkeypatch.setenv("OLLAMA_GEN_MODEL", OLLAMA_MODEL)


class TestStreamingChain:
    @pytest.mark.asyncio
    async def test_ollama_skipped_when_no_model_is_configured(self):
        ollama = _ollama_client(stream=_ollama_stream(["never"]))
        groq_client = _groq_client(stream_tokens=["Groq ", "answer."])
        with patch.object(OllamaConnector, "_get_async_ollama", return_value=ollama), \
             patch.object(OllamaConnector, "_get_async_groq", return_value=groq_client):
            chunks = await _collect(OllamaConnector._stream_completion("prompt", 100))
        assert _text(chunks) == "Groq answer."
        ollama.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_ollama_used_first_when_configured(self, ollama_enabled):
        ollama = _ollama_client(stream=_ollama_stream(["Local ", "answer."]))
        groq_client = _groq_client(stream_tokens=["unused"])
        with patch.object(OllamaConnector, "_get_async_ollama", return_value=ollama), \
             patch.object(OllamaConnector, "_get_async_groq", return_value=groq_client):
            chunks = await _collect(OllamaConnector._stream_completion("prompt", 100))
        assert _text(chunks) == "Local answer."
        assert _sentinel(chunks)["_model"] == OLLAMA_MODEL
        assert ollama.chat.call_args.kwargs["options"] == {"num_predict": 100}
        groq_client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_ollama_length_cutoff_is_reported_as_truncated(self, ollama_enabled):
        ollama = _ollama_client(stream=_ollama_stream(["Cut ", "off"], done_reason="length"))
        with patch.object(OllamaConnector, "_get_async_ollama", return_value=ollama):
            chunks = await _collect(OllamaConnector._stream_completion("prompt", 100))
        assert _sentinel(chunks)["_finish_reason"] == "length"

    @pytest.mark.asyncio
    async def test_ollama_error_falls_back_to_groq_without_alert(self, ollama_enabled, mock_enqueue):
        ollama = _ollama_client(raises=ConnectionError("ollama not running"))
        groq_client = _groq_client(stream_tokens=["Groq ", "answer."])
        with patch.object(OllamaConnector, "_get_async_ollama", return_value=ollama), \
             patch.object(OllamaConnector, "_get_async_groq", return_value=groq_client):
            chunks = await _collect(OllamaConnector._stream_completion("prompt", 100))
        assert _text(chunks) == "Groq answer."
        mock_enqueue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ollama_that_never_starts_falls_back_after_first_chunk_timeout(self, ollama_enabled, monkeypatch):
        monkeypatch.setattr(connector_module, "_OLLAMA_FIRST_CHUNK_TIMEOUT_SECONDS", 0.05)
        ollama = _ollama_client(stream=_ollama_stream(["too late"], delay=5))
        groq_client = _groq_client(stream_tokens=["Groq ", "answer."])
        with patch.object(OllamaConnector, "_get_async_ollama", return_value=ollama), \
             patch.object(OllamaConnector, "_get_async_groq", return_value=groq_client):
            chunks = await asyncio.wait_for(
                _collect(OllamaConnector._stream_completion("prompt", 100)), timeout=2,
            )
        assert _text(chunks) == "Groq answer."

    @pytest.mark.asyncio
    async def test_ollama_failure_mid_stream_does_not_restart_on_groq(self, ollama_enabled):
        ollama = _ollama_client(stream=_ollama_stream(["Partial ", "more"], fail_after=1))
        groq_client = _groq_client(stream_tokens=["Groq"])
        with patch.object(OllamaConnector, "_get_async_ollama", return_value=ollama), \
             patch.object(OllamaConnector, "_get_async_groq", return_value=groq_client):
            chunks = await _collect(OllamaConnector._stream_completion("prompt", 100))
        assert _text(chunks) == "Partial "
        assert _sentinel(chunks)["_model"] == OLLAMA_MODEL
        groq_client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_groq_key_skips_groq_without_alert(self, ollama_enabled, mock_enqueue):
        ollama = _ollama_client(raises=ConnectionError("ollama not running"))
        gemini = _gemini(text="Gemini answer.")
        with patch.object(OllamaConnector, "_get_async_ollama", return_value=ollama), \
             patch.object(OllamaConnector, "_get_async_groq", return_value=None), \
             patch.object(OllamaConnector, "gemini", gemini):
            chunks = await _collect(OllamaConnector._stream_completion("prompt", 100))
        assert _text(chunks) == "Gemini answer."
        mock_enqueue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_all_providers_failing_names_each_one(self, ollama_enabled):
        ollama = _ollama_client(raises=ConnectionError("ollama down"))
        gemini = _gemini(raises=RuntimeError("gemini down"))
        with patch.object(OllamaConnector, "_get_async_ollama", return_value=ollama), \
             patch.object(OllamaConnector, "_get_async_groq", return_value=None), \
             patch.object(OllamaConnector, "gemini", gemini):
            with pytest.raises(ValueError) as excinfo:
                await _collect(OllamaConnector._stream_completion("prompt", 100))
        message = str(excinfo.value)
        assert "ollama down" in message
        assert "GROQ_API_KEY is not set" in message
        assert "gemini down" in message


class TestCompleteChain:
    @pytest.mark.asyncio
    async def test_ollama_reply_is_used_first(self, ollama_enabled):
        ollama = _ollama_client(reply="  Local reply  ")
        groq_client = _groq_client(reply="unused")
        with patch.object(OllamaConnector, "_get_async_ollama", return_value=ollama), \
             patch.object(OllamaConnector, "_get_async_groq", return_value=groq_client):
            result = await OllamaConnector.complete("prompt", 50, label="test")
        assert result == "Local reply"
        groq_client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_ollama_reply_falls_through_to_groq(self, ollama_enabled):
        ollama = _ollama_client(reply="")
        groq_client = _groq_client(reply="Groq reply")
        with patch.object(OllamaConnector, "_get_async_ollama", return_value=ollama), \
             patch.object(OllamaConnector, "_get_async_groq", return_value=groq_client):
            result = await OllamaConnector.complete("prompt", 50, label="test")
        assert result == "Groq reply"

    @pytest.mark.asyncio
    async def test_groq_still_gets_low_reasoning_effort(self):
        groq_client = _groq_client(reply="Groq reply")
        with patch.object(OllamaConnector, "_get_async_groq", return_value=groq_client):
            await OllamaConnector.complete("prompt", 50, label="test")
        assert groq_client.chat.completions.create.call_args.kwargs["reasoning_effort"] == "low"

    @pytest.mark.asyncio
    async def test_missing_groq_key_goes_to_gemini(self):
        gemini = _gemini(text="Gemini reply")
        with patch.object(OllamaConnector, "_get_async_groq", return_value=None), \
             patch.object(OllamaConnector, "gemini", gemini):
            result = await OllamaConnector.complete("prompt", 50, label="test")
        assert result == "Gemini reply"

    @pytest.mark.asyncio
    async def test_returns_none_when_everything_fails(self, ollama_enabled):
        ollama = _ollama_client(raises=ConnectionError("down"))
        groq_client = _groq_client(raises=RuntimeError("down"))
        gemini = _gemini(raises=RuntimeError("down"))
        with patch.object(OllamaConnector, "_get_async_ollama", return_value=ollama), \
             patch.object(OllamaConnector, "_get_async_groq", return_value=groq_client), \
             patch.object(OllamaConnector, "gemini", gemini):
            assert await OllamaConnector.complete("prompt", 50, label="test") is None

    @pytest.mark.asyncio
    async def test_generate_title_uses_the_chain(self, ollama_enabled):
        ollama = _ollama_client(reply='"Warburg Effect Basics."')
        with patch.object(OllamaConnector, "_get_async_ollama", return_value=ollama):
            title = await OllamaConnector.generate_title("What is the Warburg effect?")
        assert title == "Warburg Effect Basics"

    @pytest.mark.asyncio
    async def test_generate_title_falls_back_to_heuristic_when_everything_fails(self):
        gemini = _gemini(raises=RuntimeError("down"))
        with patch.object(OllamaConnector, "_get_async_groq", return_value=None), \
             patch.object(OllamaConnector, "gemini", gemini):
            title = await OllamaConnector.generate_title("what is the warburg effect?")
        assert title == "What is the warburg effect"


class TestUrlClassificationUsesChain:
    @pytest.mark.asyncio
    async def test_yes_reply_classifies_as_cancer_related(self):
        from src.jobs.url_classification import _classify
        with patch.object(OllamaConnector, "complete", AsyncMock(return_value="Yes")) as complete:
            related, raw = await _classify("Glioblastoma treatment outcomes ...")
        assert (related, raw) == (True, "yes")
        # 10 tokens left no room for a reasoning model's hidden reasoning.
        assert complete.call_args.kwargs["max_tokens"] >= 100

    @pytest.mark.asyncio
    async def test_no_provider_answering_raises_instead_of_rejecting(self):
        from src.jobs.url_classification import _classify
        with patch.object(OllamaConnector, "complete", AsyncMock(return_value=None)):
            with pytest.raises(RuntimeError):
                await _classify("Some page")
