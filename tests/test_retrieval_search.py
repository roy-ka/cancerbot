"""Tests for src.retrieval.search.search_sources query construction.

Covers the full_text_word_count filter that excludes short sources from
retrieval without deleting them from the index.
"""
from unittest.mock import MagicMock

from src.retrieval.search import search_sources, MIN_FULLTEXT_WORDS


def _make_db(hits=None):
    db = MagicMock()
    db.search.return_value = {"hits": {"hits": hits or [], "total": {"value": len(hits or [])}}}
    return db


class TestFullTextWordCountFilter:
    def test_query_filters_on_full_text_word_count(self):
        db = _make_db()
        search_sources(db, text="glioblastoma treatment", vector=[0.1, 0.2])

        _, kwargs = db.search.call_args
        body = kwargs["body"]
        filters = body["query"]["bool"]["filter"]
        assert {"range": {"full_text_word_count": {"gte": MIN_FULLTEXT_WORDS}}} in filters

    def test_filter_present_even_with_text_only_query(self):
        db = _make_db()
        search_sources(db, text="glioblastoma treatment", vector=None)

        _, kwargs = db.search.call_args
        body = kwargs["body"]
        filters = body["query"]["bool"]["filter"]
        assert {"range": {"full_text_word_count": {"gte": MIN_FULLTEXT_WORDS}}} in filters

    def test_returns_deduped_hits_unaffected_by_filter_addition(self):
        hits = [
            {"_id": "a:c0", "_source": {"id": "a:c0", "source_id": "a"}, "_score": 1.0},
            {"_id": "a:c1", "_source": {"id": "a:c1", "source_id": "a"}, "_score": 0.9},
            {"_id": "b:c0", "_source": {"id": "b:c0", "source_id": "b"}, "_score": 0.8},
        ]
        db = _make_db(hits)
        result = search_sources(db, text="cancer", vector=[0.1], k_results=5)

        assert [h["_source"]["source_id"] for h in result] == ["a", "b"]
