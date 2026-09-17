"""Tests for src/classes/ollama_connector.py — Groq/Gemini timeout + fallback.

See the 2026-09-16 stuck-message incident (traced via Axiom): neither the
Groq nor the Gemini client had a timeout configured, so a stalled connection
hung the request forever — nothing was ever raised, so `except
groq.GroqError` never fired, the Gemini fallback never triggered, and
nothing was ever logged. These tests pin the fix:

- Groq's own timeout exception (APITimeoutError) is a GroqError subclass,
  so configuring a client-level timeout makes a stall raise something the
  existing `except groq.GroqError` already catches.
- Both the Groq and Gemini clients are actually constructed with a timeout.
- The Gemini fallback call uses the async client surface (.aio), not the
  sync one — the sync one would block the whole event loop, not just the
  one hung request, while stalled.
"""
import httpx
import groq
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.classes.ollama_connector import (
    OllamaConnector,
    _GeminiClientProxy,
    _GROQ_TIMEOUT_SECONDS,
    _GEMINI_TIMEOUT_SECONDS,
)


class TestGroqTimeoutExceptionHierarchy:
    def test_api_timeout_error_is_a_groq_error(self):
        """The fix depends on this holding: _stream_completion only catches
        `groq.GroqError`, not asyncio.TimeoutError or a bare hang. If the SDK
        ever stopped making APITimeoutError a GroqError subclass, a timeout
        would once again raise something the except clause doesn't catch,
        silently reintroducing the hang."""
        assert issubclass(groq.APITimeoutError, groq.GroqError)


class TestClientsConstructedWithTimeout:
    def test_async_groq_client_constructed_with_timeout(self, monkeypatch):
        monkeypatch.setattr(OllamaConnector, "_async_groq", None)
        with patch("groq.AsyncGroq") as mock_async_groq:
            OllamaConnector._get_async_groq()

        _, kwargs = mock_async_groq.call_args
        assert kwargs.get("timeout") == _GROQ_TIMEOUT_SECONDS

    def test_sync_groq_client_constructed_with_timeout(self, monkeypatch):
        from src.classes.ollama_connector import _GroqClientProxy

        monkeypatch.setattr(_GroqClientProxy, "_client", None)
        monkeypatch.setenv("GROQ_API_KEY", "dummy-key")
        with patch("src.classes.ollama_connector.Groq") as mock_groq:
            OllamaConnector.groq._ensure_client()

        _, kwargs = mock_groq.call_args
        assert kwargs.get("timeout") == _GROQ_TIMEOUT_SECONDS

    def test_gemini_client_constructed_with_timeout(self, monkeypatch):
        monkeypatch.setattr(_GeminiClientProxy, "_client", None)
        monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
        with patch("src.classes.ollama_connector.google_genai.Client") as mock_client:
            OllamaConnector.gemini._ensure_client()

        _, kwargs = mock_client.call_args
        http_options = kwargs.get("http_options")
        assert http_options is not None
        # HttpOptions.timeout is in milliseconds.
        assert http_options.timeout == int(_GEMINI_TIMEOUT_SECONDS * 1000)


class TestStreamCompletionFallsBackOnGroqTimeout:
    @pytest.mark.asyncio
    async def test_falls_back_to_gemini_via_async_client(self, monkeypatch):
        """A Groq timeout (the exact exception a configured client-level
        timeout now raises on a stall) must still trigger the existing
        Gemini fallback, and that fallback must go through the async
        (.aio) client surface, not the sync one."""
        timeout_exc = groq.APITimeoutError(request=httpx.Request("POST", "https://api.groq.com/x"))

        mock_groq_client = MagicMock()
        mock_groq_client.chat.completions.create = AsyncMock(side_effect=timeout_exc)
        monkeypatch.setattr(
            OllamaConnector, "_get_async_groq", classmethod(lambda cls: mock_groq_client)
        )

        fake_response = MagicMock()
        fake_response.text = "Gemini says hello [source1]"
        fake_response.candidates = []

        mock_gemini = MagicMock()
        mock_gemini.aio.models.generate_content = AsyncMock(return_value=fake_response)
        mock_gemini.models.generate_content = MagicMock(
            side_effect=AssertionError("sync Gemini call must not be used — it blocks the event loop")
        )
        monkeypatch.setattr(OllamaConnector, "gemini", mock_gemini)

        with patch("src.classes.ollama_connector.enqueue", new=AsyncMock()) as mock_enqueue:
            chunks = []
            async for chunk in OllamaConnector._stream_completion("prompt text", max_tokens=100):
                chunks.append(chunk)

        assert "Gemini says hello [source1]" in chunks
        mock_gemini.aio.models.generate_content.assert_awaited_once()
        mock_gemini.models.generate_content.assert_not_called()
        mock_enqueue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_when_both_providers_fail(self, monkeypatch):
        timeout_exc = groq.APITimeoutError(request=httpx.Request("POST", "https://api.groq.com/x"))
        mock_groq_client = MagicMock()
        mock_groq_client.chat.completions.create = AsyncMock(side_effect=timeout_exc)
        monkeypatch.setattr(
            OllamaConnector, "_get_async_groq", classmethod(lambda cls: mock_groq_client)
        )

        mock_gemini = MagicMock()
        mock_gemini.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("gemini also down"))
        monkeypatch.setattr(OllamaConnector, "gemini", mock_gemini)

        with patch("src.classes.ollama_connector.enqueue", new=AsyncMock()):
            with pytest.raises(ValueError, match="AI generation unavailable"):
                async for _ in OllamaConnector._stream_completion("prompt text", max_tokens=100):
                    pass
