"""Tests for src.retrieval.search.search_sources query construction and fusion.

Covers the full_text_word_count filter that excludes short sources from
retrieval without deleting them from the index, the tag-based
evidence/recency/disease-area boosting, the Reciprocal Rank Fusion that
combines the dense and lexical halves, and cross-source DOI dedup.
"""
import re
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.retrieval.search import (
    search_sources,
    MIN_FULLTEXT_WORDS,
    EXCLUDED_PUB_TYPES,
    HIGH_EVIDENCE_MIN,
    RECENT_YEARS,
    RRF_K,
    MIN_COSINE,
    MAX_RESULTS,
    _score_to_cosine,
)


def _hit(id_, score=1.0, **source_fields):
    source = {"id": id_, "source_id": re.sub(r":c\d+$", "", id_)}
    source.update(source_fields)
    return {"_id": id_, "_score": score, "_source": source}


def _probe_hit(id_, cosine):
    """A probe hit whose raw KNN score decodes back to the given cosine.
    OpenSearch's cosinesimil returns _score = (1 + cos) / 2."""
    return _hit(id_, score=(cosine + 1.0) / 2.0)


def _response(hits):
    return {"hits": {"hits": list(hits), "total": {"value": len(hits)}}}


def _make_db(*responses):
    """Mock connector. Defaults to two empty responses so body-construction
    tests get one per sub-query."""
    db = MagicMock()
    db.msearch.return_value = list(responses) if responses else [_response([]), _response([])]
    return db


def _bodies(db):
    _, kwargs = db.msearch.call_args
    return kwargs["bodies"]


def _is_probe(body):
    """The relevance probe puts its knn clause directly under `must`; the
    dense/lexical ranking sub-queries wrap their match clauses in a nested
    bool. That structural difference is the reliable discriminator."""
    return "knn" in body["query"]["bool"]["must"][0]


def _ranking_bodies(db):
    """The dense + lexical sub-queries that are actually rank-fused, excluding
    the read-only cosine probe."""
    return [b for b in _bodies(db) if not _is_probe(b)]


def _probe(db):
    probes = [b for b in _bodies(db) if _is_probe(b)]
    return probes[0] if probes else None


def _dense_and_lexical(db):
    """Split the ranking sub-queries by which match clause they carry."""
    dense = lexical = None
    for body in _ranking_bodies(db):
        clauses = body["query"]["bool"]["must"][0]["bool"]["should"]
        if any("knn" in c for c in clauses):
            dense = body
        else:
            lexical = body
    return dense, lexical


class TestSubQuerySplit:
    """The hybrid query is issued as two independent ranked lists in one
    msearch round trip, so they can be rank-fused rather than score-blended."""

    def test_two_sub_queries_issued_in_one_round_trip(self):
        db = _make_db()
        search_sources(db, text="glioblastoma", vector=[0.1, 0.2])

        assert db.msearch.call_count == 1
        # dense + lexical are fused; the probe rides along in the same round trip
        assert len(_ranking_bodies(db)) == 2
        assert _probe(db) is not None
        dense, lexical = _dense_and_lexical(db)
        assert dense is not None and lexical is not None

    def test_dense_carries_vector_and_lexical_carries_text(self):
        db = _make_db()
        search_sources(db, text="glioblastoma", vector=[0.1, 0.2])
        dense, lexical = _dense_and_lexical(db)

        knn = dense["query"]["bool"]["must"][0]["bool"]["should"][0]["knn"]["embedding"]
        assert knn["vector"] == [0.1, 0.2]

        matches = lexical["query"]["bool"]["must"][0]["bool"]["should"]
        assert [list(m.keys())[0] for m in matches] == ["match", "match"]
        assert matches[0]["match"]["content_for_embedding"]["query"] == "glioblastoma"
        assert matches[1]["match"]["title"]["query"] == "glioblastoma"

    def test_text_and_vector_may_describe_the_query_differently(self):
        """run_retrieval embeds the natural question while passing terms for
        BM25 — the two halves must not be assumed to share a string."""
        db = _make_db()
        search_sources(db, text="glioblastoma temozolomide", vector=[0.5])
        dense, lexical = _dense_and_lexical(db)

        assert dense["query"]["bool"]["must"][0]["bool"]["should"][0]["knn"]["embedding"]["vector"] == [0.5]
        assert lexical["query"]["bool"]["must"][0]["bool"]["should"][0]["match"][
            "content_for_embedding"]["query"] == "glioblastoma temozolomide"

    def test_vector_only_issues_dense_alone(self):
        db = _make_db(_response([]))
        search_sources(db, text=None, vector=[0.1])
        dense, lexical = _dense_and_lexical(db)

        assert len(_ranking_bodies(db)) == 1
        assert dense is not None and lexical is None
        # a vector query still carries the relevance probe
        assert _probe(db) is not None

    def test_text_only_issues_lexical_alone(self):
        db = _make_db(_response([]))
        search_sources(db, text="cancer", vector=None)
        dense, lexical = _dense_and_lexical(db)

        assert len(_ranking_bodies(db)) == 1
        assert lexical is not None and dense is None
        # no vector means no cosine to read, so no probe
        assert _probe(db) is None

    def test_neither_text_nor_vector_searches_nothing(self):
        db = _make_db()
        assert search_sources(db, text=None, vector=None) == []
        db.msearch.assert_not_called()

    def test_oversized_fetch_leaves_room_for_dedup(self):
        db = _make_db()
        search_sources(db, text="cancer", vector=[0.1], k_results=5)

        for body in _bodies(db):
            assert body["size"] == 20

    def test_embedding_never_requested_in_source(self):
        """A 768-float array is ~15KB of JSON per hit."""
        db = _make_db()
        search_sources(db, text="cancer", vector=[0.1])

        for body in _bodies(db):
            assert "embedding" not in body["_source"]
        for body in _ranking_bodies(db):
            assert "doi" in body["_source"]  # needed for cross-source dedup


class TestSharedEnvelopeOnBothSubQueries:
    """Every filter/boost/exclusion must ride on both halves — otherwise one
    list could surface a doc the other would have excluded."""

    def test_word_count_filter_on_both(self):
        db = _make_db()
        search_sources(db, text="glioblastoma treatment", vector=[0.1, 0.2])

        for body in _bodies(db):
            filters = body["query"]["bool"]["filter"]
            assert {"range": {"full_text_word_count": {"gte": MIN_FULLTEXT_WORDS}}} in filters

    def test_filter_present_even_with_text_only_query(self):
        db = _make_db(_response([]))
        search_sources(db, text="glioblastoma treatment", vector=None)

        filters = _bodies(db)[0]["query"]["bool"]["filter"]
        assert {"range": {"full_text_word_count": {"gte": MIN_FULLTEXT_WORDS}}} in filters

    def test_excluded_pub_types_are_must_not_on_both(self):
        db = _make_db()
        search_sources(db, text="cancer", vector=[0.1])

        for body in _bodies(db):
            assert {"terms": {"pub_types": EXCLUDED_PUB_TYPES}} in body["query"]["bool"]["must_not"]


class TestMatchingSeparatedFromScoring:
    """Matching must live in `must`, boosting in `should`. If boost clauses sat
    alongside the match clauses under a shared minimum_should_match=1, a doc
    could qualify on a boost alone (e.g. merely being recent) without matching
    the query at all."""

    def test_match_clauses_are_under_must_not_should(self):
        db = _make_db()
        search_sources(db, text="glioblastoma", vector=[0.1])

        for body in _ranking_bodies(db):
            inner = body["query"]["bool"]["must"][0]["bool"]
            assert inner["minimum_should_match"] == 1

    def test_outer_should_has_no_minimum_should_match(self):
        db = _make_db()
        search_sources(db, text="glioblastoma", vector=[0.1])

        for body in _ranking_bodies(db):
            bool_q = body["query"]["bool"]
            # Boost-only clauses must never be able to satisfy matching on their own
            assert "minimum_should_match" not in bool_q
            assert len(bool_q["should"]) >= 4


class TestEvidenceAndRecencyBoosts:
    def test_high_evidence_boost_clause_present(self):
        db = _make_db()
        search_sources(db, text="cancer", vector=[0.1])
        shoulds = _bodies(db)[0]["query"]["bool"]["should"]

        evidence_clauses = [c for c in shoulds if "range" in c and "evidence_level" in c["range"]]
        assert any(c["range"]["evidence_level"]["gte"] == HIGH_EVIDENCE_MIN for c in evidence_clauses)

    def test_recency_boost_uses_current_year(self):
        db = _make_db()
        search_sources(db, text="cancer", vector=[0.1])
        shoulds = _bodies(db)[0]["query"]["bool"]["should"]

        year_clauses = [c for c in shoulds if "range" in c and "pub_year" in c["range"]]
        current_year = datetime.now(timezone.utc).year
        assert any(c["range"]["pub_year"]["gte"] == current_year - RECENT_YEARS for c in year_clauses)


class TestDiseaseAreaBoost:
    def test_disease_area_clause_added_when_provided(self):
        db = _make_db()
        search_sources(db, text="GBM", vector=[0.1], disease_areas=["Brain Cancer"])
        shoulds = _bodies(db)[0]["query"]["bool"]["should"]

        area_clauses = [c for c in shoulds if "terms" in c and "disease_areas" in c["terms"]]
        assert len(area_clauses) == 1
        assert area_clauses[0]["terms"]["disease_areas"] == ["brain cancer"]

    def test_no_disease_area_clause_when_absent(self):
        db = _make_db()
        search_sources(db, text="cancer", vector=[0.1])
        shoulds = _bodies(db)[0]["query"]["bool"]["should"]

        assert not [c for c in shoulds if "terms" in c and "disease_areas" in c["terms"]]


class TestGracefulDegradationForUntaggedDocs:
    """The whole pre-existing corpus lacks these fields. Boosts must be
    `should` and the pub-type exclusion `must_not`, so an untagged doc is
    ranked lower but never made unreachable — the failure mode the
    full_text_word_count filter originally caused."""

    def test_new_metadata_never_appears_as_a_positive_filter(self):
        db = _make_db()
        search_sources(db, text="cancer", vector=[0.1], disease_areas=["brain cancer"])

        for body in _bodies(db):
            filtered_fields = set()
            for clause in body["query"]["bool"]["filter"]:
                for filter_body in clause.values():
                    filtered_fields.update(filter_body.keys())

            # Only the (already backfilled) word-count field may gate matching
            assert filtered_fields == {"full_text_word_count"}
            for field in ("evidence_level", "pub_year", "disease_areas", "pub_types"):
                assert field not in filtered_fields


class TestChunkDedup:
    def test_one_chunk_per_source(self):
        hits = [_hit("a:c0"), _hit("a:c1"), _hit("b:c0")]
        db = _make_db(_response(hits), _response([]))
        result = search_sources(db, text="cancer", vector=[0.1], k_results=5)

        assert [h["_source"]["source_id"] for h in result] == ["a", "b"]

    def test_extra_chunks_do_not_earn_extra_fusion_credit(self):
        """Two chunks of the same source at ranks 1-2 must not let it collect
        two RRF contributions, and must not push the next source's rank down."""
        hits = [_hit("a:c0"), _hit("a:c1"), _hit("b:c0")]
        db = _make_db(_response(hits), _response([]))
        result = search_sources(db, text="cancer", vector=[0.1], k_results=5)

        by_id = {h["_source"]["source_id"]: h for h in result}
        assert by_id["a"]["_score"] == 1.0 / (RRF_K + 1)
        # b is rank 2 after a's chunks collapse, not rank 3
        assert by_id["b"]["_score"] == 1.0 / (RRF_K + 2)

    def test_legacy_docs_without_source_id_dedupe_on_stripped_id(self):
        legacy = [
            {"_id": "old:c0", "_score": 1.0, "_source": {"id": "old:c0"}},
            {"_id": "old:c1", "_score": 0.9, "_source": {"id": "old:c1"}},
        ]
        db = _make_db(_response(legacy), _response([]))
        result = search_sources(db, text="cancer", vector=[0.1])

        assert len(result) == 1


class TestReciprocalRankFusion:
    def test_agreement_between_lists_beats_a_single_top_hit(self):
        dense = [_hit("a:c0"), _hit("b:c0"), _hit("c:c0")]
        lexical = [_hit("b:c0"), _hit("c:c0"), _hit("a:c0")]
        db = _make_db(_response(dense), _response(lexical))
        result = search_sources(db, text="cancer", vector=[0.1], k_results=5)

        # b: ranks 2 + 1 beats a: ranks 1 + 3
        assert [h["_source"]["source_id"] for h in result][0] == "b"

    def test_raw_score_magnitude_does_not_decide_ranking(self):
        """The point of rank fusion: BM25 is unbounded and KNN cosine is not,
        so a huge BM25 score must not outrank a doc both lists surfaced."""
        dense = [_hit("b:c0", score=0.5), _hit("a:c0", score=0.4)]
        lexical = [_hit("a:c0", score=9999.0), _hit("c:c0", score=9998.0)]
        db = _make_db(_response(dense), _response(lexical))
        result = search_sources(db, text="cancer", vector=[0.1], k_results=5)

        ids = [h["_source"]["source_id"] for h in result]
        assert ids[0] == "a"          # in both lists
        assert ids.index("b") < ids.index("c")  # 0.5 cosine outranks a 9998 BM25 score

    def test_fused_score_replaces_per_modality_score(self):
        dense = [_hit("a:c0", score=17.3)]
        db = _make_db(_response(dense), _response([]))
        result = search_sources(db, text="cancer", vector=[0.1])

        assert result[0]["_score"] == 1.0 / (RRF_K + 1)
        assert result[0]["_component_ranks"] == {"dense": 1}

    def test_component_ranks_record_both_lists(self):
        db = _make_db(_response([_hit("a:c0")]), _response([_hit("a:c0")]))
        result = search_sources(db, text="cancer", vector=[0.1])

        assert result[0]["_component_ranks"] == {"dense": 1, "lexical": 1}
        assert result[0]["_score"] == 2.0 / (RRF_K + 1)

    def test_results_trimmed_to_k(self):
        dense = [_hit(f"s{i}:c0") for i in range(10)]
        db = _make_db(_response(dense), _response([]))
        result = search_sources(db, text="cancer", vector=[0.1], k_results=3)

        assert len(result) == 3


class TestSubQueryFailureDegradesGracefully:
    """msearch reports a failing sub-query inline instead of raising, so one
    broken half must degrade to single-modality search, not lose everything."""

    def test_failed_dense_still_returns_lexical_results(self):
        db = _make_db({"error": {"type": "search_phase_execution_exception"}},
                      _response([_hit("a:c0")]))
        result = search_sources(db, text="cancer", vector=[0.1])

        assert [h["_source"]["source_id"] for h in result] == ["a"]
        assert result[0]["_component_ranks"] == {"lexical": 1}

    def test_all_sub_queries_failing_returns_empty(self):
        db = _make_db({"error": "boom"}, {"error": "boom"})
        assert search_sources(db, text="cancer", vector=[0.1]) == []

    def test_msearch_raising_is_swallowed(self):
        db = MagicMock()
        db.msearch.side_effect = RuntimeError("OpenSearch not available")

        assert search_sources(db, text="cancer", vector=[0.1]) == []


class TestCrossSourceDoiDedup:
    """The same paper routinely returns from PubMed as pmid:… and from
    CrossRef as doi:… — distinct source_ids, one abstract. Without this the
    LLM sees it twice and can cite it as two independent sources."""

    def test_same_doi_under_different_source_ids_collapses(self):
        dense = [
            _hit("pmid:123:c0", doi="10.1000/abc"),
            _hit("doi:10.1000/abc:c0", doi="10.1000/abc"),
        ]
        db = _make_db(_response(dense), _response([]))
        result = search_sources(db, text="cancer", vector=[0.1], k_results=5)

        assert len(result) == 1
        assert result[0]["_source"]["source_id"] == "pmid:123"  # the better-ranked one

    def test_doi_matching_is_case_and_whitespace_insensitive(self):
        dense = [
            _hit("pmid:123:c0", doi="10.1000/ABC"),
            _hit("doi:10.1000/abc:c0", doi="  10.1000/abc  "),
        ]
        db = _make_db(_response(dense), _response([]))
        result = search_sources(db, text="cancer", vector=[0.1])

        assert len(result) == 1

    def test_sources_without_doi_are_untouched(self):
        """Most of the corpus predates DOI capture — absence must not collapse
        unrelated sources together."""
        dense = [_hit("url:aaa:c0"), _hit("url:bbb:c0"), _hit("nct:NCT1:c0")]
        db = _make_db(_response(dense), _response([]))
        result = search_sources(db, text="cancer", vector=[0.1], k_results=5)

        assert len(result) == 3

    def test_distinct_dois_are_kept(self):
        dense = [_hit("pmid:1:c0", doi="10.1/a"), _hit("pmid:2:c0", doi="10.1/b")]
        db = _make_db(_response(dense), _response([]))
        result = search_sources(db, text="cancer", vector=[0.1], k_results=5)

        assert len(result) == 2

    def test_dedup_survives_to_fill_k(self):
        """Dropping a duplicate must not leave a short result set when more
        unique sources were available further down."""
        dense = [
            _hit("pmid:1:c0", doi="10.1/a"),
            _hit("doi:10.1/a:c0", doi="10.1/a"),
            _hit("pmid:2:c0", doi="10.1/b"),
        ]
        db = _make_db(_response(dense), _response([]))
        result = search_sources(db, text="cancer", vector=[0.1], k_results=2)

        assert [h["_source"]["source_id"] for h in result] == ["pmid:1", "pmid:2"]


class TestRelevanceProbe:
    """A vector query issues a third, read-only KNN sub-query with no `should`
    boosts, so its _score is the clean cosine used for the relevance floor."""

    def test_probe_has_no_scoring_boosts(self):
        db = _make_db()
        search_sources(db, text="cancer", vector=[0.1])

        probe = _probe(db)
        assert probe is not None
        # the boosted dense list would carry a `should`; the probe must not,
        # or its _score stops being a clean cosine
        assert "should" not in probe["query"]["bool"]

    def test_probe_keeps_the_filter_envelope(self):
        """The probe must never surface a doc the real query would exclude."""
        db = _make_db()
        search_sources(db, text="cancer", vector=[0.1])

        probe = _probe(db)
        assert {"range": {"full_text_word_count": {"gte": MIN_FULLTEXT_WORDS}}} \
            in probe["query"]["bool"]["filter"]
        assert {"terms": {"pub_types": EXCLUDED_PUB_TYPES}} \
            in probe["query"]["bool"]["must_not"]

    def test_probe_fetches_only_identity_fields(self):
        db = _make_db()
        search_sources(db, text="cancer", vector=[0.1])

        assert set(_probe(db)["_source"]) == {"source_id", "id"}

    def test_score_to_cosine_inverts_opensearch_scoring(self):
        # _score = (1 + cos) / 2  ->  cos = 2*score - 1
        assert _score_to_cosine(1.0) == 1.0
        assert _score_to_cosine(0.9) == pytest.approx(0.8)
        assert _score_to_cosine(0.5) == 0.0


class TestRelevanceThreshold:
    """Instead of a fixed top-k, the result count tracks how much the corpus
    actually has to say: keep every source whose best-chunk cosine clears
    MIN_COSINE, capped at k_results, with a top-1 fallback so a borderline
    query never hands the LLM an empty context."""

    def test_sources_below_the_floor_are_dropped(self):
        dense = [_hit("a:c0"), _hit("b:c0"), _hit("c:c0")]
        probe = [
            _probe_hit("a:c0", MIN_COSINE + 0.2),
            _probe_hit("b:c0", MIN_COSINE - 0.2),   # below floor
            _probe_hit("c:c0", MIN_COSINE + 0.1),
        ]
        db = _make_db(_response(dense), _response([]), _response(probe))
        result = search_sources(db, text="cancer", vector=[0.1])

        assert [h["_source"]["source_id"] for h in result] == ["a", "c"]

    def test_exactly_at_the_floor_is_kept(self):
        dense = [_hit("a:c0")]
        db = _make_db(_response(dense), _response([]),
                      _response([_probe_hit("a:c0", MIN_COSINE)]))
        result = search_sources(db, text="cancer", vector=[0.1])

        assert [h["_source"]["source_id"] for h in result] == ["a"]

    def test_variable_count_grows_with_relevance(self):
        """A query the corpus richly covers returns more than a sparse one."""
        rich = [_hit(f"s{i}:c0") for i in range(6)]
        rich_probe = [_probe_hit(f"s{i}:c0", MIN_COSINE + 0.1) for i in range(6)]
        db = _make_db(_response(rich), _response([]), _response(rich_probe))
        assert len(search_sources(db, text="cancer", vector=[0.1])) == 6

        sparse = [_hit("s0:c0"), _hit("s1:c0")]
        sparse_probe = [
            _probe_hit("s0:c0", MIN_COSINE + 0.1),
            _probe_hit("s1:c0", MIN_COSINE - 0.1),
        ]
        db = _make_db(_response(sparse), _response([]), _response(sparse_probe))
        assert len(search_sources(db, text="cancer", vector=[0.1])) == 1

    def test_result_count_is_capped_at_k_results(self):
        dense = [_hit(f"s{i}:c0") for i in range(MAX_RESULTS + 5)]
        probe = [_probe_hit(f"s{i}:c0", MIN_COSINE + 0.1) for i in range(MAX_RESULTS + 5)]
        db = _make_db(_response(dense), _response([]), _response(probe))
        result = search_sources(db, text="cancer", vector=[0.1], k_results=3)

        assert len(result) == 3

    def test_nothing_clears_floor_falls_back_to_top_one(self):
        """Never starve the LLM: keep the single best-ranked source so it can
        still answer (or correctly decline) rather than seeing nothing."""
        dense = [_hit("a:c0"), _hit("b:c0")]
        probe = [
            _probe_hit("a:c0", MIN_COSINE - 0.1),
            _probe_hit("b:c0", MIN_COSINE - 0.2),
        ]
        db = _make_db(_response(dense), _response([]), _response(probe))
        result = search_sources(db, text="cancer", vector=[0.1])

        assert [h["_source"]["source_id"] for h in result] == ["a"]

    def test_relevance_cosine_is_attached_to_each_hit(self):
        dense = [_hit("a:c0")]
        db = _make_db(_response(dense), _response([]),
                      _response([_probe_hit("a:c0", 0.75)]))
        result = search_sources(db, text="cancer", vector=[0.1])

        assert result[0]["_relevance_cosine"] == pytest.approx(0.75)

    def test_best_chunk_cosine_wins_when_source_probed_twice(self):
        """A source's floor decision uses its highest-scoring chunk, so one weak
        chunk can't sink a source another chunk clears."""
        dense = [_hit("a:c0")]
        probe = [
            _probe_hit("a:c0", MIN_COSINE - 0.2),
            _probe_hit("a:c1", MIN_COSINE + 0.2),   # same source, better chunk
        ]
        db = _make_db(_response(dense), _response([]), _response(probe))
        result = search_sources(db, text="cancer", vector=[0.1])

        assert [h["_source"]["source_id"] for h in result] == ["a"]

    def test_no_probe_means_no_gating(self):
        """A lexical-only query (no vector, e.g. a URL-title search) has no
        cosine to read, so every fused source is kept."""
        lexical = [_hit("a:c0"), _hit("b:c0"), _hit("c:c0")]
        db = _make_db(_response(lexical))
        result = search_sources(db, text="cancer", vector=None)

        assert len(result) == 3
        assert all(h["_relevance_cosine"] is None for h in result)


class TestSearchMetrics:
    """Scores are recorded raw. They were multiplied by 100 and cast to int on
    the assumption that OpenSearch returned 0-1 scores; it never did, so every
    row held a meaningless ~500-2000. With RRF scores (~0.01-0.03) an int
    column would truncate all of them to 0."""

    def test_scores_are_stored_raw_not_scaled(self):
        from src.retrieval import calculate_search_metrics

        results = [{"_score": 0.0328}, {"_score": 0.0161}]
        metrics = calculate_search_metrics("cancer", results)

        assert metrics["top_score"] == 0.0328
        assert metrics["min_score"] == 0.0161
        assert abs(metrics["avg_score"] - 0.02445) < 1e-9
        assert metrics["result_count"] == 2

    def test_small_scores_survive_instead_of_truncating_to_zero(self):
        from src.retrieval import calculate_search_metrics

        metrics = calculate_search_metrics("cancer", [{"_score": 1.0 / (RRF_K + 1)}])
        assert metrics["top_score"] > 0

    def test_empty_results_give_none_scores(self):
        from src.retrieval import calculate_search_metrics

        metrics = calculate_search_metrics("cancer", [])
        assert metrics["result_count"] == 0
        assert metrics["top_score"] is None
        assert metrics["avg_score"] is None
        assert metrics["min_score"] is None

    def test_missing_score_field_treated_as_zero(self):
        from src.retrieval import calculate_search_metrics

        metrics = calculate_search_metrics("cancer", [{"_source": {}}])
        assert metrics["min_score"] == 0

    def test_query_is_truncated_for_the_column(self):
        from src.retrieval import calculate_search_metrics

        metrics = calculate_search_metrics("x" * 900, [])
        assert len(metrics["search_query"]) == 500


class TestRerankSources:
    """_rerank_sources reorders search_sources' output by cross-encoder
    score — a precision pass on an already-gated list, not a second filter
    (see src/retrieval/__init__.py's docstring for why it must never drop a
    source the cosine gate already let through)."""

    def _sources(self):
        return [
            {"_source": {"id": "a", "content_for_embedding": "about topic A"}, "_score": 0.03},
            {"_source": {"id": "b", "content_for_embedding": "about topic B"}, "_score": 0.02},
            {"_source": {"id": "c", "content_for_embedding": "about topic C"}, "_score": 0.01},
        ]

    def test_reorders_by_rerank_score_descending(self, monkeypatch):
        from src.retrieval import _rerank_sources

        monkeypatch.setenv("RERANK_ENABLED", "true")
        monkeypatch.setattr("src.nlp.rerank", lambda query, documents: [0.1, 0.9, 0.5])

        result = _rerank_sources("question", self._sources())

        assert [s["_source"]["id"] for s in result] == ["b", "c", "a"]
        assert result[0]["_rerank_score"] == 0.9

    def test_disabled_leaves_order_unchanged(self, monkeypatch):
        from src.retrieval import _rerank_sources

        monkeypatch.setenv("RERANK_ENABLED", "false")
        sources = self._sources()

        result = _rerank_sources("question", sources)

        assert result is sources
        assert "_rerank_score" not in result[0]

    def test_rerank_failure_leaves_order_unchanged(self, monkeypatch):
        """rerank() itself already fails open (returns None) on any HTTP
        error — this confirms the caller respects that instead of crashing
        on a None score list."""
        from src.retrieval import _rerank_sources

        monkeypatch.setenv("RERANK_ENABLED", "true")
        monkeypatch.setattr("src.nlp.rerank", lambda query, documents: None)
        sources = self._sources()

        result = _rerank_sources("question", sources)

        assert [s["_source"]["id"] for s in result] == ["a", "b", "c"]

    def test_fewer_than_two_sources_skips_rerank_call(self, monkeypatch):
        from src.retrieval import _rerank_sources

        monkeypatch.setenv("RERANK_ENABLED", "true")
        called = []
        monkeypatch.setattr("src.nlp.rerank", lambda query, documents: called.append(1) or [1.0])

        result = _rerank_sources("question", self._sources()[:1])

        assert called == []
        assert len(result) == 1
