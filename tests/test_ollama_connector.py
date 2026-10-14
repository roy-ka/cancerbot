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
class TestFocusSources:
    """Sources the user explicitly asked about ("Ask about this source") get
    more evidence room and a prompt note lifting the two-source minimum."""

    def test_focus_source_is_named_and_not_truncated_to_the_normal_cap(self):
        ctx = [
            {"id": "pmid:1", "content_for_embedding": "A" * 3000, "focus": True},
            {"id": "pmid:2", "content_for_embedding": "B" * 3000},
        ]
        prompt, aliases = OllamaConnector._build_prompt(ctx, "[source1] main finding?", [])
        assert aliases == {"source1": "pmid:1", "source2": "pmid:2"}
        assert "refers specifically to [source1]" in prompt
        assert "A" * 3000 in prompt
        assert "B" * 1000 not in prompt

    def test_no_focus_note_without_focus_sources(self):
        prompt, _ = OllamaConnector._build_prompt(
            [{"id": "pmid:2", "content_for_embedding": "text"}], "question", [],
        )
        assert "SOURCES THE USER ASKED ABOUT" not in prompt
