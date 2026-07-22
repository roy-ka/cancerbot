"""Tests for NLP term extraction and stop-word removal.

Covers:
- extract_terms(): HTTP client behaviour, response parsing, error handling
- TestStopWordRemoval: stop-word constants, filtering logic, edge cases
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.routers.conversation_helper import (
    _TERM_STOP_WORDS,
    _dedupe_terms,
    _extract_terms_from_message,
    _extract_term_groups_from_message,
)


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
    async def test_extract_with_groups_returns_terms_and_groups(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "expanded_entities": ["Mebendazole", "GBM"],
            "synonyms": ["glioblastoma", "glioblastoma multiforme"],
            "entity_groups": [
                {"term": "Mebendazole", "synonyms": []},
                {"term": "GBM", "synonyms": ["glioblastoma", "glioblastoma multiforme"]},
            ],
        }

        with patch("src.nlp._get_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_fn.return_value = mock_client

            from src.nlp import extract_with_groups
            terms, groups = await extract_with_groups("Can Mebendazole help against GBM?")

        assert "Mebendazole" in terms
        assert "GBM" in terms
        assert len(groups) == 2
        assert {g["term"] for g in groups} == {"Mebendazole", "GBM"}

    @pytest.mark.asyncio
    async def test_extract_with_groups_missing_field_returns_empty_groups(self):
        """Older/unpatched NLP service responses without entity_groups shouldn't error."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "expanded_entities": ["cancer"],
            "synonyms": [],
        }

        with patch("src.nlp._get_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_fn.return_value = mock_client

            from src.nlp import extract_with_groups
            terms, groups = await extract_with_groups("cancer")

        assert terms == ["cancer"]
        assert groups == []

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
# TestSpellingCorrectionBeforeExtraction
# ---------------------------------------------------------------------------

class TestSpellingCorrectionBeforeExtraction:
    """conversation_helper's extraction wrappers must run correct_spelling on
    the message text before handing it to the NLP extractor, so a merged-word
    typo like 'Mebendazolehelp' becomes 'Mebendazole help' before entities are
    extracted from it."""

    @pytest.mark.asyncio
    async def test_extract_terms_from_message_uses_corrected_text(self):
        with patch("src.nlp.correct_spelling", new=AsyncMock(return_value="Mebendazole help against cancer")) as mock_correct, \
             patch("src.nlp.extract_terms", new=AsyncMock(return_value=["Mebendazole", "cancer"])) as mock_extract:
            result = await _extract_terms_from_message("Mebendazolehelp against cancer")

        mock_correct.assert_awaited_once_with("Mebendazolehelp against cancer")
        mock_extract.assert_awaited_once_with("Mebendazole help against cancer")
        assert result == ["Mebendazole", "cancer"]

    @pytest.mark.asyncio
    async def test_extract_term_groups_from_message_uses_corrected_text(self):
        with patch("src.nlp.correct_spelling", new=AsyncMock(return_value="Mebendazole help against cancer")) as mock_correct, \
             patch("src.nlp.extract_with_groups", new=AsyncMock(return_value=(["Mebendazole", "cancer"], []))) as mock_extract:
            terms, groups = await _extract_term_groups_from_message("Mebendazolehelp against cancer")

        mock_correct.assert_awaited_once_with("Mebendazolehelp against cancer")
        mock_extract.assert_awaited_once_with("Mebendazole help against cancer")
        assert terms == ["Mebendazole", "cancer"]

    @pytest.mark.asyncio
    async def test_falls_back_to_original_text_when_correction_fails(self):
        with patch("src.nlp.correct_spelling", new=AsyncMock(side_effect=Exception("nlp down"))), \
             patch("src.nlp.extract_terms", new=AsyncMock(return_value=["cancer"])) as mock_extract:
            result = await _extract_terms_from_message("cancer treatment")

        mock_extract.assert_awaited_once_with("cancer treatment")
        assert result == ["cancer"]


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
