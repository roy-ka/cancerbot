"""Tests for the full citation pipeline.

Covers:
- add_claims_and_sources(): OpenSearch hit → message.sources/claims
- OllamaConnector._post_process(): alias substitution
- run_retrieval(): strip :cN chunk suffix from returned IDs
- _TERM_STOP_WORDS filter in search_and_embed stored-terms path
"""
import re
import pytest
from unittest.mock import MagicMock, patch

from src.classes.ollama_connector import OllamaConnector
from src.db.repositories.messeges import add_claims_and_sources
from src.routers.conversation_helper import _TERM_STOP_WORDS, _dedupe_terms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hit(index: str, id_: str, source_id: str, **extra) -> dict:
    doc = {
        "id": id_,
        "source_id": source_id,
        "source_type": extra.get("source_type", "pubmed"),
        "title": extra.get("title"),
        "url": extra.get("url"),
        "pmid": extra.get("pmid"),
        "doi": extra.get("doi"),
        "content_for_embedding": extra.get("content_for_embedding", "some evidence text"),
        "evidence_score_0_5": extra.get("evidence_score_0_5"),
    }
    return {"_index": index, "_source": doc}


def _make_message(sources_ids: list[str]) -> MagicMock:
    msg = MagicMock()
    msg.id = "msg-001"
    msg.sources_ids = sources_ids
    msg.sources = None
    msg.claims = None
    return msg


# ---------------------------------------------------------------------------
# TestAddClaimsAndSources
# ---------------------------------------------------------------------------

class TestAddClaimsAndSources:
    def _run(self, hits: list[dict], sources_ids: list[str]):
        msg = _make_message(sources_ids)
        mock_response = {"hits": {"hits": hits}}
        with patch(
            "src.db.repositories.messeges.dbConnector.get_claims_and_sources_by_id",
            return_value=mock_response,
        ):
            add_claims_and_sources(msg)
        return msg

    def test_pubmed_hit_goes_to_sources(self):
        hit = _make_hit("v1.5_en_nomic_index", "pmid:123:c0", "pmid:123", pmid="123")
        msg = self._run([hit], ["pmid:123"])
        assert msg.sources is not None
        assert len(msg.sources) == 1
        assert msg.sources[0]["id"] == "pmid:123"
        assert msg.claims is None

    def test_claims_hit_goes_to_claims(self):
        hit = _make_hit("v1.5_claims_nomic_index", "doi:10.1/x:c0", "doi:10.1/x", doi="10.1/x")
        msg = self._run([hit], ["doi:10.1/x"])
        assert msg.claims is not None
        assert len(msg.claims) == 1
        assert msg.claims[0]["id"] == "doi:10.1/x"
        assert msg.sources is None

    def test_chunk_suffix_stripped_from_id(self):
        hit = _make_hit("v1.5_en_nomic_index", "pmid:999:c3", "pmid:999", pmid="999")
        msg = self._run([hit], ["pmid:999"])
        assert msg.sources[0]["id"] == "pmid:999"

    def test_duplicate_source_id_deduplicated(self):
        hit1 = _make_hit("v1.5_en_nomic_index", "pmid:42:c0", "pmid:42", pmid="42")
        hit2 = _make_hit("v1.5_en_nomic_index", "pmid:42:c1", "pmid:42", pmid="42")
        msg = self._run([hit1, hit2], ["pmid:42"])
        assert len(msg.sources) == 1

    def test_wikipedia_name_is_title(self):
        hit = _make_hit(
            "v1.5_en_nomic_index",
            "url:abcdef:c0",
            "url:abcdef",
            source_type="wikipedia",
            title="Glioblastoma",
        )
        msg = self._run([hit], ["url:abcdef"])
        assert msg.sources[0]["name"] == "Glioblastoma"

    def test_url_source_name_falls_back_to_domain(self):
        hit = _make_hit(
            "v1.5_en_nomic_index",
            "url:sha1:c0",
            "url:sha1",
            source_type="url",
            url="https://www.cancer.gov/page",
            title=None,
        )
        msg = self._run([hit], ["url:sha1"])
        assert msg.sources[0]["name"] == "cancer"

    def test_empty_sources_ids_returns_early(self):
        msg = _make_message([])
        with patch(
            "src.db.repositories.messeges.dbConnector.get_claims_and_sources_by_id"
        ) as mock_fetch:
            add_claims_and_sources(msg)
        mock_fetch.assert_not_called()
        assert msg.sources is None
        assert msg.claims is None

    def test_opensearch_exception_does_not_raise(self):
        msg = _make_message(["pmid:123"])
        with patch(
            "src.db.repositories.messeges.dbConnector.get_claims_and_sources_by_id",
            side_effect=RuntimeError("OS down"),
        ):
            add_claims_and_sources(msg)  # must not raise
        assert msg.sources is None


# ---------------------------------------------------------------------------
# TestPostProcess
# ---------------------------------------------------------------------------

class TestPostProcess:
    def test_replaces_single_alias(self):
        result = OllamaConnector._post_process(
            "Cancer involves altered metabolism [source1].",
            {"source1": "pmid:12345"},
        )
        assert "[pmid:12345]" in result
        assert "[source1]" not in result

    def test_replaces_multiple_aliases(self):
        result = OllamaConnector._post_process(
            "Effect A [source1] and effect B [source2].",
            {"source1": "pmid:1", "source2": "doi:10.1/x"},
        )
        assert "[pmid:1]" in result
        assert "[doi:10.1/x]" in result

    def test_empty_brackets_removed(self):
        result = OllamaConnector._post_process(
            "Some text [] more text.",
            {},
        )
        assert "[]" not in result

    def test_no_aliases_leaves_text_unchanged(self):
        text = "Plain answer with no citations."
        result = OllamaConnector._post_process(text, {})
        assert result == text

    def test_chunk_suffix_not_in_output(self):
        # IDs fed to _build_prompt already have :cN stripped; verify _post_process
        # doesn't re-introduce them (it only replaces aliases with whatever is in alias_to_id)
        result = OllamaConnector._post_process(
            "Evidence [source1].",
            {"source1": "pmid:777"},
        )
        assert ":c" not in result


# ---------------------------------------------------------------------------
# TestRetrievalStripsChunkSuffix
# ---------------------------------------------------------------------------

class TestRetrievalStripsChunkSuffix:
    def _mock_os_hit(self, id_with_chunk: str) -> dict:
        return {
            "_score": 0.9,
            "_index": "v1.5_en_nomic_index",
            "_source": {
                "id": id_with_chunk,
                "source_id": re.sub(r":c\d+$", "", id_with_chunk),
                "content_for_embedding": "relevant evidence",
            },
        }

    def test_chunk_suffix_stripped_from_sources_ids(self):
        from src.retrieval import run_retrieval

        hits = [self._mock_os_hit("pmid:100:c0"), self._mock_os_hit("doi:10.1/y:c2")]

        with (
            patch("src.retrieval.OllamaConnector.embed_text", return_value=[0.1] * 768),
            patch("src.retrieval.search_sources", return_value=hits),
        ):
            result = run_retrieval("glioblastoma treatment")

        assert "pmid:100" in result["sources_ids"]
        assert "doi:10.1/y" in result["sources_ids"]
        for sid in result["sources_ids"]:
            assert ":c" not in sid

    def test_missing_id_field_skipped_gracefully(self):
        from src.retrieval import run_retrieval

        hits = [{"_score": 0.5, "_index": "v1.5_en_nomic_index", "_source": {}}]

        with (
            patch("src.retrieval.OllamaConnector.embed_text", return_value=[0.1] * 768),
            patch("src.retrieval.search_sources", return_value=hits),
        ):
            result = run_retrieval("cancer")

        assert result["sources_ids"] == []


# ---------------------------------------------------------------------------
# TestTermStopWordFilter
# ---------------------------------------------------------------------------

class TestTermStopWordFilter:
    def test_common_verbs_are_stop_words(self):
        for word in ("tell", "give", "show", "explain", "describe"):
            assert word in _TERM_STOP_WORDS

    def test_request_verbs_are_stop_words(self):
        for word in ("want", "need", "help", "ask", "find"):
            assert word in _TERM_STOP_WORDS

    def test_medical_terms_not_in_stop_words(self):
        for term in ("glioblastoma", "GBM", "EGFR", "temozolomide", "cancer"):
            assert term.lower() not in _TERM_STOP_WORDS

    def test_filter_removes_stop_words_from_stored_terms(self):
        raw = ["tell", "glioblastoma", "show", "KRAS"]
        filtered = [t for t in _dedupe_terms(raw) if t.lower() not in _TERM_STOP_WORDS]
        assert "glioblastoma" in filtered
        assert "KRAS" in filtered
        assert "tell" not in filtered
        assert "show" not in filtered

    def test_filter_case_insensitive(self):
        raw = ["Tell", "GIVE", "Glioblastoma"]
        filtered = [t for t in _dedupe_terms(raw) if t.lower() not in _TERM_STOP_WORDS]
        assert "Glioblastoma" in filtered
        assert "Tell" not in filtered
        assert "GIVE" not in filtered

    def test_all_stop_words_list_yields_empty(self):
        raw = ["tell", "give", "show", "the", "and"]
        filtered = [t for t in _dedupe_terms(raw) if t.lower() not in _TERM_STOP_WORDS]
        assert filtered == []
