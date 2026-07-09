import pytest
from unittest.mock import MagicMock, patch
import groq
import openai as openai_lib

from src.classes.ollama_connector import OllamaConnector

CONTEXT = [{"id": "src-001", "content_for_embedding": "Cancer cells exhibit the Warburg effect."}]


def _make_completion(content):
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = "stop"
    completion = MagicMock()
    completion.choices = [choice]
    completion.model = "test-model"
    completion.usage.total_tokens = 50
    return completion


def _groq_mock(content=None, raises=None):
    m = MagicMock()
    if raises is not None:
        m.chat.completions.create.side_effect = raises
    else:
        m.chat.completions.create.return_value = _make_completion(content)
    return m


def _openai_mock(content=None, raises=None):
    m = MagicMock()
    if raises is not None:
        m.chat.completions.create.side_effect = raises
    else:
        m.chat.completions.create.return_value = _make_completion(content)
    return m


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


class TestGroqOpenAIFallback:
    def test_groq_success_returns_answer(self):
        mock_groq = _groq_mock(content="Warburg effect answer.")
        with patch.object(OllamaConnector, "groq", mock_groq):
            result = OllamaConnector.generate_text(CONTEXT, "What is the Warburg effect?", [])
        assert "Warburg effect answer" in result
        mock_groq.chat.completions.create.assert_called_once()

    def test_groq_rate_limit_falls_back_to_openai(self):
        mock_groq = _groq_mock(raises=_rate_limit_exc())
        mock_openai = _openai_mock(content="OpenAI fallback answer.")
        with patch.object(OllamaConnector, "groq", mock_groq), \
             patch.object(OllamaConnector, "openai", mock_openai):
            result = OllamaConnector.generate_text(CONTEXT, "What is cancer?", [])
        assert "OpenAI fallback answer" in result
        mock_openai.chat.completions.create.assert_called_once()

    def test_groq_server_error_falls_back_to_openai(self):
        mock_groq = _groq_mock(raises=_server_error_exc())
        mock_openai = _openai_mock(content="OpenAI server fallback.")
        with patch.object(OllamaConnector, "groq", mock_groq), \
             patch.object(OllamaConnector, "openai", mock_openai):
            result = OllamaConnector.generate_text(CONTEXT, "What is cancer?", [])
        assert "OpenAI server fallback" in result

    def test_openai_not_called_on_groq_success(self):
        mock_groq = _groq_mock(content="Groq answer.")
        mock_openai = _openai_mock()
        with patch.object(OllamaConnector, "groq", mock_groq), \
             patch.object(OllamaConnector, "openai", mock_openai):
            OllamaConnector.generate_text(CONTEXT, "What is cancer?", [])
        mock_openai.chat.completions.create.assert_not_called()

    def test_both_providers_fail_raises_value_error(self):
        mock_groq = _groq_mock(raises=_rate_limit_exc())
        mock_openai = _openai_mock(raises=openai_lib.RateLimitError(
            "OpenAI rate limit",
            response=MagicMock(status_code=429, headers={}),
            body={},
        ))
        with patch.object(OllamaConnector, "groq", mock_groq), \
             patch.object(OllamaConnector, "openai", mock_openai), \
             pytest.raises(ValueError, match="AI generation unavailable"):
            OllamaConnector.generate_text(CONTEXT, "What is cancer?", [])

    def test_alias_replacement_works_on_fallback_path(self):
        mock_groq = _groq_mock(raises=_rate_limit_exc())
        mock_openai = _openai_mock(content="Cancer uses glucose [R1].")
        with patch.object(OllamaConnector, "groq", mock_groq), \
             patch.object(OllamaConnector, "openai", mock_openai):
            result = OllamaConnector.generate_text(CONTEXT, "What is cancer?", [])
        assert "[src-001]" in result
        assert "[R1]" not in result
