"""Tests for NLP term extraction and stop-word removal.

Covers:
- extract_terms(): HTTP client behaviour, response parsing, error handling
- TestStopWordRemoval: stop-word constants, filtering logic, edge cases
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.routers.conversation_helper import _TERM_STOP_WORDS, _dedupe_terms


# ---------------------------------------------------------------------------
# TestExtractTerms
# ---------------------------------------------------------------------------

class TestExtractTerms:
    """Unit tests for src.nlp.extract_terms — mocks the HTTP call."""

    @pytest.mark.asyncio
    async def test_returns_merged_entities_and_synonyms(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "expanded_entities": ["glioblastoma", "GBM"],
            "synonyms": ["glioblastoma multiforme"],
        }

        with patch("src.nlp._get_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_fn.return_value = mock_client

            from src.nlp import extract_terms
            result = await extract_terms("What is GBM?")

        assert "glioblastoma" in result
        assert "GBM" in result
        assert "glioblastoma multiforme" in result

    @pytest.mark.asyncio
    async def test_empty_text_returns_empty_list(self):
        from src.nlp import extract_terms
        result = await extract_terms("")
        assert result == []

    @pytest.mark.asyncio
    async def test_http_error_returns_empty_list(self):
        import httpx

        with patch("src.nlp._get_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client_fn.return_value = mock_client

            from src.nlp import extract_terms
            result = await extract_terms("tell me about cancer")

        assert result == []

    @pytest.mark.asyncio
    async def test_deduplicates_terms(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "expanded_entities": ["KRAS", "KRAS"],
            "synonyms": ["KRAS"],
        }

        with patch("src.nlp._get_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_fn.return_value = mock_client

            from src.nlp import extract_terms
            result = await extract_terms("KRAS mutation")

        assert result.count("KRAS") == 1


# ---------------------------------------------------------------------------
# TestStopWordRemoval
# ---------------------------------------------------------------------------

class TestStopWordRemoval:
    """Tests for the _TERM_STOP_WORDS filter used in search_and_embed."""

    def test_common_request_verbs_are_stop_words(self):
        for word in ("tell", "give", "show", "explain", "describe", "list", "find"):
            assert word in _TERM_STOP_WORDS, f"'{word}' should be a stop word"

    def test_common_function_words_are_stop_words(self):
        for word in ("the", "and", "or", "is", "are", "was", "with", "for"):
            assert word in _TERM_STOP_WORDS, f"'{word}' should be a stop word"

    def test_medical_terms_not_stop_words(self):
        for term in ("glioblastoma", "gbm", "egfr", "temozolomide", "cancer", "kras"):
            assert term not in _TERM_STOP_WORDS, f"'{term}' must NOT be a stop word"

    def test_filter_preserves_medical_terms(self):
        terms = ["tell", "glioblastoma", "show", "KRAS", "explain", "temozolomide"]
        filtered = [t for t in terms if t.lower() not in _TERM_STOP_WORDS]
        assert filtered == ["glioblastoma", "KRAS", "temozolomide"]

    def test_filter_case_insensitive(self):
        terms = ["Tell", "GIVE", "Glioblastoma", "SHOW", "EGFR"]
        filtered = [t for t in terms if t.lower() not in _TERM_STOP_WORDS]
        assert "Glioblastoma" in filtered
        assert "EGFR" in filtered
        assert "Tell" not in filtered
        assert "GIVE" not in filtered
        assert "SHOW" not in filtered

    def test_all_stop_words_yields_empty_after_filter(self):
        terms = ["tell", "give", "the", "and", "or", "show"]
        filtered = [t for t in terms if t.lower() not in _TERM_STOP_WORDS]
        assert filtered == []

    def test_dedupe_then_filter_removes_duplicates_and_stops(self):
        terms = ["KRAS", "kras", "tell", "Tell", "glioblastoma"]
        deduped = _dedupe_terms(terms)
        filtered = [t for t in deduped if t.lower() not in _TERM_STOP_WORDS]
        # "KRAS" and "kras" are the same after dedup (case-insensitive key)
        assert len([t for t in filtered if t.lower() == "kras"]) == 1
        assert "glioblastoma" in filtered
        assert not any(t.lower() == "tell" for t in filtered)
