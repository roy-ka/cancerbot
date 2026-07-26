"""Tests for src.retrieval.search.search_sources query construction.

Covers the full_text_word_count filter that excludes short sources from
retrieval without deleting them from the index, plus the tag-based
evidence/recency/disease-area boosting.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.retrieval.search import (
    search_sources,
    MIN_FULLTEXT_WORDS,
    EXCLUDED_PUB_TYPES,
    HIGH_EVIDENCE_MIN,
    RECENT_YEARS,
)


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


def _bool_body(db):
    _, kwargs = db.search.call_args
    return kwargs["body"]["query"]["bool"]


class TestMatchingSeparatedFromScoring:
    """Matching must live in `must`, boosting in `should`. If boost clauses sat
    alongside the match clauses under a shared minimum_should_match=1, a doc
    could qualify on a boost alone (e.g. merely being recent) without matching
    the query at all."""

    def test_match_clauses_are_under_must_not_should(self):
        db = _make_db()
        search_sources(db, text="glioblastoma", vector=[0.1])
        bool_q = _bool_body(db)

        inner = bool_q["must"][0]["bool"]
        assert inner["minimum_should_match"] == 1
        clause_types = [list(c.keys())[0] for c in inner["should"]]
        assert "knn" in clause_types
        assert clause_types.count("match") == 2

    def test_outer_should_has_no_minimum_should_match(self):
        db = _make_db()
        search_sources(db, text="glioblastoma", vector=[0.1])
        bool_q = _bool_body(db)

        # Boost-only clauses must never be able to satisfy matching on their own
        assert "minimum_should_match" not in bool_q
        assert len(bool_q["should"]) >= 4


class TestEvidenceAndRecencyBoosts:
    def test_high_evidence_boost_clause_present(self):
        db = _make_db()
        search_sources(db, text="cancer", vector=[0.1])
        shoulds = _bool_body(db)["should"]

        evidence_clauses = [c for c in shoulds if "range" in c and "evidence_level" in c["range"]]
        assert any(c["range"]["evidence_level"]["gte"] == HIGH_EVIDENCE_MIN for c in evidence_clauses)

    def test_recency_boost_uses_current_year(self):
        db = _make_db()
        search_sources(db, text="cancer", vector=[0.1])
        shoulds = _bool_body(db)["should"]

        year_clauses = [c for c in shoulds if "range" in c and "pub_year" in c["range"]]
        current_year = datetime.now(timezone.utc).year
        assert any(c["range"]["pub_year"]["gte"] == current_year - RECENT_YEARS for c in year_clauses)

    def test_excluded_pub_types_are_must_not(self):
        db = _make_db()
        search_sources(db, text="cancer", vector=[0.1])
        bool_q = _bool_body(db)

        assert {"terms": {"pub_types": EXCLUDED_PUB_TYPES}} in bool_q["must_not"]


class TestDiseaseAreaBoost:
    def test_disease_area_clause_added_when_provided(self):
        db = _make_db()
        search_sources(db, text="GBM", vector=[0.1], disease_areas=["Brain Cancer"])
        shoulds = _bool_body(db)["should"]

        area_clauses = [c for c in shoulds if "terms" in c and "disease_areas" in c["terms"]]
        assert len(area_clauses) == 1
        assert area_clauses[0]["terms"]["disease_areas"] == ["brain cancer"]

    def test_no_disease_area_clause_when_absent(self):
        db = _make_db()
        search_sources(db, text="cancer", vector=[0.1])
        shoulds = _bool_body(db)["should"]

        assert not [c for c in shoulds if "terms" in c and "disease_areas" in c["terms"]]


class TestGracefulDegradationForUntaggedDocs:
    """The whole pre-existing corpus lacks these fields. Boosts must be
    `should` and the pub-type exclusion `must_not`, so an untagged doc is
    ranked lower but never made unreachable — the failure mode the
    full_text_word_count filter originally caused."""

    def test_new_metadata_never_appears_as_a_positive_filter(self):
        db = _make_db()
        search_sources(db, text="cancer", vector=[0.1], disease_areas=["brain cancer"])
        filters = _bool_body(db)["filter"]

        filtered_fields = set()
        for clause in filters:
            for body in clause.values():
                filtered_fields.update(body.keys())

        # Only the (already backfilled) word-count field may gate matching
        assert filtered_fields == {"full_text_word_count"}
        for field in ("evidence_level", "pub_year", "disease_areas", "pub_types"):
            assert field not in filtered_fields
