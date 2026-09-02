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

def _make_source(title="Cancer study", content=None, pmid="12345", doi=None):
    return {
        "source_type": "pubmed",
        "pmid": pmid,
        "doi": doi,
        "title": title,
        "content_for_embedding": content or " ".join(["word"] * 50),
        "abstract_source": "pubmed",
        "url": None,
    }


def _setup_db(monkeypatch, already_indexed=None, existing_doi_base_ids=None):
    mock_db = MagicMock()
    mock_db.existing_base_source_ids.return_value = already_indexed or set()
    mock_db.existing_doi_base_ids.return_value = existing_doi_base_ids or {}
    mock_db.bulk_index_to_db.side_effect = lambda index_name, docs: (len(list(docs)), [])
    mock_db.create_index.return_value = None
    monkeypatch.setattr("src.routers.conversation_helper.dbConnector", lambda: mock_db)
    return mock_db


def _indexed_docs(mock_db) -> list:
    """Every chunk document handed to OpenSearch, in order.

    Chunks are embedded and written as one bulk batch rather than one call per
    chunk, so the docs come from the single bulk_index_to_db call.
    """
    docs = []
    for call in mock_db.bulk_index_to_db.call_args_list:
        docs.extend(call.args[1])
    return docs


def _patch_embeddings():
    """Patch the batch embedder — one vector back per input chunk."""
    return patch(
        "src.routers.conversation_helper.OllamaConnector.embed_texts",
        side_effect=lambda texts: [[0.1] * 768 for _ in texts],
    )


class TestEmbedAndIndexSources:
    def test_chunk_id_has_chunk_suffix(self, monkeypatch):
        mock_db = _setup_db(monkeypatch)
        with _patch_embeddings():
            _embed_and_index_sources([_make_source()], terms=["cancer"])
        doc = _indexed_docs(mock_db)[0]
        assert ":c0" in doc["id"]

    def test_source_id_field_is_base_id(self, monkeypatch):
        mock_db = _setup_db(monkeypatch)
        with _patch_embeddings():
            _embed_and_index_sources([_make_source(pmid="99999")], terms=["cancer"])
        doc = _indexed_docs(mock_db)[0]
        assert doc["source_id"] == "pmid:99999"
        assert doc["id"] == "pmid:99999:c0"

    def test_tags_are_search_terms(self, monkeypatch):
        mock_db = _setup_db(monkeypatch)
        with _patch_embeddings():
            _embed_and_index_sources([_make_source()], terms=["lung cancer", "egfr"])
        doc = _indexed_docs(mock_db)[0]
        assert doc["tags"] == ["lung cancer", "egfr"]

    def test_tags_empty_when_no_terms(self, monkeypatch):
        mock_db = _setup_db(monkeypatch)
        with _patch_embeddings():
            _embed_and_index_sources([_make_source()], terms=[])
        doc = _indexed_docs(mock_db)[0]
        assert doc["tags"] == []

    def test_full_text_stored_on_doc(self, monkeypatch):
        content = " ".join(["word"] * 50)
        mock_db = _setup_db(monkeypatch)
        with _patch_embeddings():
            _embed_and_index_sources([_make_source(content=content)], terms=["cancer"])
        doc = _indexed_docs(mock_db)[0]
        assert doc["full_text"] == content

    def test_long_source_produces_multiple_chunks(self, monkeypatch):
        content = " ".join(["word"] * 300)
        mock_db = _setup_db(monkeypatch)
        with _patch_embeddings():
            _embed_and_index_sources([_make_source(content=content)], terms=["cancer"])
        docs = _indexed_docs(mock_db)
        assert len(docs) == 3
        ids = [d["id"] for d in docs]
        assert ids == ["pmid:12345:c0", "pmid:12345:c1", "pmid:12345:c2"]

    def test_skips_already_indexed_source(self, monkeypatch):
        mock_db = _setup_db(monkeypatch, already_indexed={"pmid:12345"})
        with _patch_embeddings():
            indexed, skipped = _embed_and_index_sources([_make_source()], terms=["cancer"])
        assert indexed == 0
        assert skipped == 1
        mock_db.bulk_index_to_db.assert_not_called()

    def test_dedup_uses_existing_base_source_ids(self, monkeypatch):
        mock_db = _setup_db(monkeypatch)
        with _patch_embeddings():
            _embed_and_index_sources([_make_source()], terms=["cancer"])
        mock_db.existing_base_source_ids.assert_called_once_with(["pmid:12345"])

    def test_chunk_index_field_set_correctly(self, monkeypatch):
        content = " ".join(["word"] * 300)
        mock_db = _setup_db(monkeypatch)
        with _patch_embeddings():
            _embed_and_index_sources([_make_source(content=content)], terms=[])
        indices = [d["chunk_index"] for d in _indexed_docs(mock_db)]
        assert indices == [0, 1, 2]


# ---------------------------------------------------------------------------
# _embed_and_index_sources — DOI double-indexing prevention
#
# _stable_source_id prefers pmid over doi, so the same real article can end
# up as pmid:X from PubMed and doi:Y from CrossRef — two different base_ids
# for one paper, invisible to a bare base_id-equality dedup check.
# ---------------------------------------------------------------------------

class TestEmbedAndIndexSourcesDoiDedup:
    def test_in_batch_doi_duplicate_is_skipped(self, monkeypatch):
        """Same batch: a PubMed source (pmid:X, doi=Y) and a CrossRef source
        (no pmid, doi=Y) for the same paper — only the first-seen indexes."""
        mock_db = _setup_db(monkeypatch)
        pubmed_source = _make_source(pmid="12345", doi="10.1/abc")
        crossref_source = _make_source(pmid=None, doi="10.1/abc", title="Same paper via CrossRef")
        with _patch_embeddings():
            indexed, skipped = _embed_and_index_sources(
                [pubmed_source, crossref_source], terms=["cancer"]
            )
        assert skipped == 1
        docs = _indexed_docs(mock_db)
        base_ids = {d["source_id"] for d in docs}
        assert base_ids == {"pmid:12345"}

    def test_doi_case_and_whitespace_insensitive_in_batch(self, monkeypatch):
        mock_db = _setup_db(monkeypatch)
        first = _make_source(pmid="1", doi="10.1/ABC")
        second = _make_source(pmid=None, doi=" 10.1/abc ", title="Duplicate, different casing")
        with _patch_embeddings():
            _embed_and_index_sources([first, second], terms=["cancer"])
        docs = _indexed_docs(mock_db)
        assert {d["source_id"] for d in docs} == {"pmid:1"}

    def test_sources_without_doi_are_unaffected(self, monkeypatch):
        """No doi on either source — nothing for the DOI check to match on,
        both index normally (distinct pmids)."""
        mock_db = _setup_db(monkeypatch)
        with _patch_embeddings():
            indexed, skipped = _embed_and_index_sources(
                [_make_source(pmid="1"), _make_source(pmid="2", title="Other")], terms=["cancer"]
            )
        assert skipped == 0
        docs = _indexed_docs(mock_db)
        assert {d["source_id"] for d in docs} == {"pmid:1", "pmid:2"}

    def test_cross_batch_doi_duplicate_is_skipped(self, monkeypatch):
        """This message's only candidate has a DOI already indexed under a
        different base_id from an earlier message — existing_base_source_ids
        alone wouldn't catch this since the id itself doesn't match."""
        mock_db = _setup_db(
            monkeypatch,
            existing_doi_base_ids={"10.1/abc": "doi:10.1/abc"},
        )
        source = _make_source(pmid="12345", doi="10.1/abc")
        with _patch_embeddings():
            indexed, skipped = _embed_and_index_sources([source], terms=["cancer"])
        assert indexed == 0
        assert skipped == 1
        mock_db.bulk_index_to_db.assert_not_called()

    def test_existing_doi_base_ids_queried_with_batch_dois_only(self, monkeypatch):
        mock_db = _setup_db(monkeypatch)
        with _patch_embeddings():
            _embed_and_index_sources(
                [_make_source(pmid="1", doi="10.1/x"), _make_source(pmid="2", doi=None, title="No DOI")],
                terms=["cancer"],
            )
        mock_db.existing_doi_base_ids.assert_called_once_with({"10.1/x"})

    def test_existing_doi_base_ids_not_queried_when_no_dois_in_batch(self, monkeypatch):
        mock_db = _setup_db(monkeypatch)
        with _patch_embeddings():
            _embed_and_index_sources([_make_source(pmid="1", doi=None)], terms=["cancer"])
        mock_db.existing_doi_base_ids.assert_not_called()
