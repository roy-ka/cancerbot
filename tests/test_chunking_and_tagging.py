"""Tests for source chunking, tagging, and source_id-based deduplication."""
import pytest
from unittest.mock import MagicMock, patch

from src.routers.conversation_helper import _chunk_text, _embed_and_index_sources
from src.retrieval.db_connector import dbConnector


# ---------------------------------------------------------------------------
# _chunk_text
# ---------------------------------------------------------------------------

class TestChunkText:
    def test_short_text_returns_single_chunk(self):
        text = " ".join(["word"] * 100)
        chunks = _chunk_text(text, max_words=150, overlap=40)
        assert chunks == [text]

    def test_exact_max_words_returns_single_chunk(self):
        text = " ".join(["word"] * 150)
        chunks = _chunk_text(text, max_words=150, overlap=40)
        assert len(chunks) == 1

    def test_long_text_produces_multiple_chunks(self):
        text = " ".join(str(i) for i in range(300))
        chunks = _chunk_text(text, max_words=150, overlap=40)
        assert len(chunks) == 3

    def test_overlap_is_preserved(self):
        words = [str(i) for i in range(200)]
        text = " ".join(words)
        chunks = _chunk_text(text, max_words=150, overlap=40)
        # Last 40 words of chunk 0 should be the first 40 words of chunk 1
        end_of_first = chunks[0].split()[-40:]
        start_of_second = chunks[1].split()[:40]
        assert end_of_first == start_of_second

    def test_all_words_covered(self):
        words = [str(i) for i in range(250)]
        text = " ".join(words)
        chunks = _chunk_text(text, max_words=150, overlap=40)
        last_word = words[-1]
        assert any(last_word in c for c in chunks)

    def test_empty_text_returns_single_empty_chunk(self):
        assert _chunk_text("") == [""]


# ---------------------------------------------------------------------------
# _embed_and_index_sources — chunk IDs and tagging
# ---------------------------------------------------------------------------

def _make_source(title="Cancer study", content=None, pmid="12345"):
    return {
        "source_type": "pubmed",
        "pmid": pmid,
        "doi": None,
        "title": title,
        "content_for_embedding": content or " ".join(["word"] * 50),
        "abstract_source": "pubmed",
        "url": None,
    }


def _setup_db(monkeypatch, already_indexed=None):
    mock_db = MagicMock()
    mock_db.existing_base_source_ids.return_value = already_indexed or set()
    mock_db.index_to_db.return_value = {"_id": "test"}
    mock_db.create_index.return_value = None
    monkeypatch.setattr("src.routers.conversation_helper.dbConnector", lambda: mock_db)
    return mock_db


class TestEmbedAndIndexSources:
    def test_chunk_id_has_chunk_suffix(self, monkeypatch):
        mock_db = _setup_db(monkeypatch)
        with patch("src.routers.conversation_helper.OllamaConnector.embed_text", return_value=[0.1] * 768):
            _embed_and_index_sources([_make_source()], terms=["cancer"])
        doc = mock_db.index_to_db.call_args[0][1]
        assert ":c0" in doc["id"]

    def test_source_id_field_is_base_id(self, monkeypatch):
        mock_db = _setup_db(monkeypatch)
        with patch("src.routers.conversation_helper.OllamaConnector.embed_text", return_value=[0.1] * 768):
            _embed_and_index_sources([_make_source(pmid="99999")], terms=["cancer"])
        doc = mock_db.index_to_db.call_args[0][1]
        assert doc["source_id"] == "pmid:99999"
        assert doc["id"] == "pmid:99999:c0"

    def test_tags_are_search_terms(self, monkeypatch):
        mock_db = _setup_db(monkeypatch)
        with patch("src.routers.conversation_helper.OllamaConnector.embed_text", return_value=[0.1] * 768):
            _embed_and_index_sources([_make_source()], terms=["lung cancer", "egfr"])
        doc = mock_db.index_to_db.call_args[0][1]
        assert doc["tags"] == ["lung cancer", "egfr"]

    def test_tags_empty_when_no_terms(self, monkeypatch):
        mock_db = _setup_db(monkeypatch)
        with patch("src.routers.conversation_helper.OllamaConnector.embed_text", return_value=[0.1] * 768):
            _embed_and_index_sources([_make_source()], terms=[])
        doc = mock_db.index_to_db.call_args[0][1]
        assert doc["tags"] == []

    def test_full_text_stored_on_doc(self, monkeypatch):
        content = " ".join(["word"] * 50)
        mock_db = _setup_db(monkeypatch)
        with patch("src.routers.conversation_helper.OllamaConnector.embed_text", return_value=[0.1] * 768):
            _embed_and_index_sources([_make_source(content=content)], terms=["cancer"])
        doc = mock_db.index_to_db.call_args[0][1]
        assert doc["full_text"] == content

    def test_long_source_produces_multiple_chunks(self, monkeypatch):
        content = " ".join(["word"] * 300)
        mock_db = _setup_db(monkeypatch)
        with patch("src.routers.conversation_helper.OllamaConnector.embed_text", return_value=[0.1] * 768):
            _embed_and_index_sources([_make_source(content=content)], terms=["cancer"])
        assert mock_db.index_to_db.call_count == 3
        ids = [c[0][1]["id"] for c in mock_db.index_to_db.call_args_list]
        assert ids == ["pmid:12345:c0", "pmid:12345:c1", "pmid:12345:c2"]

    def test_skips_already_indexed_source(self, monkeypatch):
        mock_db = _setup_db(monkeypatch, already_indexed={"pmid:12345"})
        with patch("src.routers.conversation_helper.OllamaConnector.embed_text", return_value=[0.1] * 768):
            indexed, skipped = _embed_and_index_sources([_make_source()], terms=["cancer"])
        assert indexed == 0
        assert skipped == 1
        mock_db.index_to_db.assert_not_called()

    def test_dedup_uses_existing_base_source_ids(self, monkeypatch):
        mock_db = _setup_db(monkeypatch)
        with patch("src.routers.conversation_helper.OllamaConnector.embed_text", return_value=[0.1] * 768):
            _embed_and_index_sources([_make_source()], terms=["cancer"])
        mock_db.existing_base_source_ids.assert_called_once_with(["pmid:12345"])

    def test_chunk_index_field_set_correctly(self, monkeypatch):
        content = " ".join(["word"] * 300)
        mock_db = _setup_db(monkeypatch)
        with patch("src.routers.conversation_helper.OllamaConnector.embed_text", return_value=[0.1] * 768):
            _embed_and_index_sources([_make_source(content=content)], terms=[])
        indices = [c[0][1]["chunk_index"] for c in mock_db.index_to_db.call_args_list]
        assert indices == [0, 1, 2]
