import pytest
from unittest.mock import MagicMock, patch
import groq

from src.classes.ollama_connector import OllamaConnector

CONTEXT = [{"id": "src-001", "content_for_embedding": "Cancer cells exhibit the Warburg effect."}]


def _make_groq_completion(content):
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = "stop"
    completion = MagicMock()
    completion.choices = [choice]
    completion.model = "test-model"
    completion.usage.total_tokens = 50
    return completion


def _make_gemini_response(content):
    response = MagicMock()
    response.text = content
    return response


def _groq_mock(content=None, raises=None):
    m = MagicMock()
    if raises is not None:
        m.chat.completions.create.side_effect = raises
    else:
        m.chat.completions.create.return_value = _make_groq_completion(content)
    return m


def _gemini_mock(content=None, raises=None):
    m = MagicMock()
    if raises is not None:
        m.models.generate_content.side_effect = raises
    else:
        m.models.generate_content.return_value = _make_gemini_response(content)
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


class TestGroqGeminiFallback:
    def test_groq_success_returns_answer(self):
        mock_groq = _groq_mock(content="Warburg effect answer.")
        with patch.object(OllamaConnector, "groq", mock_groq):
            result = OllamaConnector.generate_text(CONTEXT, "What is the Warburg effect?", [])
        assert "Warburg effect answer" in result
        mock_groq.chat.completions.create.assert_called_once()

    def test_groq_rate_limit_falls_back_to_gemini(self):
        mock_groq = _groq_mock(raises=_rate_limit_exc())
        mock_gemini = _gemini_mock(content="Gemini fallback answer.")
        with patch.object(OllamaConnector, "groq", mock_groq), \
             patch.object(OllamaConnector, "gemini", mock_gemini):
            result = OllamaConnector.generate_text(CONTEXT, "What is cancer?", [])
        assert "Gemini fallback answer" in result
        mock_gemini.models.generate_content.assert_called_once()

    def test_groq_server_error_falls_back_to_gemini(self):
        mock_groq = _groq_mock(raises=_server_error_exc())
        mock_gemini = _gemini_mock(content="Gemini server fallback.")
        with patch.object(OllamaConnector, "groq", mock_groq), \
             patch.object(OllamaConnector, "gemini", mock_gemini):
            result = OllamaConnector.generate_text(CONTEXT, "What is cancer?", [])
        assert "Gemini server fallback" in result

    def test_gemini_not_called_on_groq_success(self):
        mock_groq = _groq_mock(content="Groq answer.")
        mock_gemini = _gemini_mock()
        with patch.object(OllamaConnector, "groq", mock_groq), \
             patch.object(OllamaConnector, "gemini", mock_gemini):
            OllamaConnector.generate_text(CONTEXT, "What is cancer?", [])
        mock_gemini.models.generate_content.assert_not_called()

    def test_both_providers_fail_raises_value_error(self):
        mock_groq = _groq_mock(raises=_rate_limit_exc())
        mock_gemini = _gemini_mock(raises=Exception("Gemini unavailable"))
        with patch.object(OllamaConnector, "groq", mock_groq), \
             patch.object(OllamaConnector, "gemini", mock_gemini), \
             pytest.raises(ValueError, match="AI generation unavailable"):
            OllamaConnector.generate_text(CONTEXT, "What is cancer?", [])

    def test_alias_replacement_works_on_fallback_path(self):
        mock_groq = _groq_mock(raises=_rate_limit_exc())
        mock_gemini = _gemini_mock(content="Cancer uses glucose [source1].")
        with patch.object(OllamaConnector, "groq", mock_groq), \
             patch.object(OllamaConnector, "gemini", mock_gemini):
            result = OllamaConnector.generate_text(CONTEXT, "What is cancer?", [])
        assert "[src-001]" in result
        assert "[source1]" not in result
