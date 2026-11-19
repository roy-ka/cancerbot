"""Tests for the LLM-based semantic search-term generation that replaces the
scispaCy entity extraction on the retrieval path.

Covers:
- OllamaConnector.generate_search_terms — JSON parsing, fenced output,
  synonym/term dedup, category passthrough, and fail-safe on bad output.
- _generate_search_term_groups — falls back to NLP extraction when the LLM
  yields nothing, so retrieval is never left blind.
- _search_terms_provider — default and override.
- _merge_entity_groups — preserves category (drives disease_areas and the
  boolean query's category OR term).
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

from src.classes.ollama_connector import OllamaConnector
from src.routers.conversation_helper import (
    _build_boolean_term_query,
    _generate_search_term_groups,
    _merge_entity_groups,
    _search_terms_provider,
)


def _complete_returning(value):
    """Patch OllamaConnector.complete to return `value` (a str or None)."""
    return patch.object(OllamaConnector, "complete", new=AsyncMock(return_value=value))


class TestGenerateSearchTerms:
    @pytest.mark.asyncio
    async def test_parses_valid_json_into_groups_and_flat_terms(self):
        payload = json.dumps({
            "groups": [
                {"term": "glioblastoma", "synonyms": ["GBM", "glioblastoma multiforme"],
                 "kind": "condition", "category": "brain cancer"},
                {"term": "temozolomide", "synonyms": ["TMZ"], "kind": "drug", "category": ""},
            ]
        })
        with _complete_returning(payload):
            result = await OllamaConnector.generate_search_terms("brain tumor that grows after radiation")

        assert result["entity_groups"] == [
            {"term": "glioblastoma", "synonyms": ["GBM", "glioblastoma multiforme"],
             "kind": "condition", "category": "brain cancer"},
            {"term": "temozolomide", "synonyms": ["TMZ"], "kind": "drug", "category": ""},
        ]
        # Flat terms are the union of every group's term + synonyms, in order.
        assert result["terms"] == ["glioblastoma", "GBM", "glioblastoma multiforme", "temozolomide", "TMZ"]

    @pytest.mark.asyncio
    async def test_strips_markdown_json_fence(self):
        payload = (
            '```json\n{"groups": [{"term": "melanoma", "synonyms": [], '
            '"kind": "condition", "category": "melanoma"}]}\n```'
        )
        with _complete_returning(payload):
            result = await OllamaConnector.generate_search_terms("skin cancer spreading")
        assert result["entity_groups"] == [
            {"term": "melanoma", "synonyms": [], "kind": "condition", "category": "melanoma"}
        ]
        assert result["terms"] == ["melanoma"]

    @pytest.mark.asyncio
    async def test_dedupes_terms_and_synonyms_case_insensitively(self):
        payload = json.dumps({
            "groups": [
                {"term": "EGFR", "synonyms": ["egfr", "EGFR mutation", "egfr"], "category": "lung cancer"},
                # Duplicate term (different case) is dropped entirely.
                {"term": "egfr", "synonyms": ["ErbB1"], "category": "lung cancer"},
            ]
        })
        with _complete_returning(payload):
            result = await OllamaConnector.generate_search_terms("lung cancer with egfr")
        assert len(result["entity_groups"]) == 1
        # The synonym equal to the term (case-insensitively) is dropped.
        assert result["entity_groups"][0]["synonyms"] == ["EGFR mutation"]
        assert result["terms"] == ["EGFR", "EGFR mutation"]

    @pytest.mark.asyncio
    async def test_skips_malformed_groups(self):
        payload = json.dumps({
            "groups": [
                "not a dict",
                {"synonyms": ["no term here"]},
                {"term": "  ", "synonyms": []},
                {"term": "osteosarcoma", "synonyms": None, "category": None},
            ]
        })
        with _complete_returning(payload):
            result = await OllamaConnector.generate_search_terms("bone cancer")
        assert result["entity_groups"] == [
            {"term": "osteosarcoma", "synonyms": [], "kind": "condition", "category": ""}
        ]
        assert result["terms"] == ["osteosarcoma"]

    @pytest.mark.asyncio
    async def test_caps_groups_synonyms_and_term_length(self):
        """The model's output becomes external-API query text and indexed
        tags, so a crafted question must not be able to produce an unbounded
        query."""
        payload = json.dumps({
            "groups": [
                {"term": f"term{i}", "synonyms": [f"syn{i}-{j}" for j in range(20)], "category": ""}
                for i in range(20)
            ] + [{"term": "x" * 500, "synonyms": [], "category": "y" * 500}]
        })
        with _complete_returning(payload):
            result = await OllamaConnector.generate_search_terms("question")

        assert len(result["entity_groups"]) == OllamaConnector._MAX_TERM_GROUPS
        for group in result["entity_groups"]:
            assert len(group["synonyms"]) <= OllamaConnector._MAX_TERM_SYNONYMS

    @pytest.mark.asyncio
    async def test_long_term_and_category_are_truncated(self):
        payload = json.dumps({"groups": [{"term": "x" * 500, "synonyms": [], "category": "y" * 500}]})
        with _complete_returning(payload):
            result = await OllamaConnector.generate_search_terms("question")
        group = result["entity_groups"][0]
        assert len(group["term"]) == OllamaConnector._MAX_TERM_CHARS
        assert len(group["category"]) == OllamaConnector._MAX_TERM_CHARS

    @pytest.mark.asyncio
    async def test_strips_query_syntax_punctuation(self):
        """Terms are interpolated raw into the PubMed/ClinicalTrials boolean
        query as `(term)`, where `[...]` is a field tag and stray parens
        unbalance the expression."""
        payload = json.dumps({
            "groups": [{
                "term": "Mebendazole (benzo[d]imidazole derivative)",
                "synonyms": ['"Vermox"'],
                "category": "",
            }]
        })
        with _complete_returning(payload):
            result = await OllamaConnector.generate_search_terms("question")
        group = result["entity_groups"][0]
        assert group["term"] == "Mebendazole benzo d imidazole derivative"
        assert group["synonyms"] == ["Vermox"]
        for value in (group["term"], *group["synonyms"]):
            assert not set(value) & set('()[]"')

    @pytest.mark.asyncio
    async def test_term_that_is_only_punctuation_is_skipped(self):
        payload = json.dumps({"groups": [{"term": "()", "synonyms": [], "category": ""}]})
        with _complete_returning(payload):
            result = await OllamaConnector.generate_search_terms("question")
        assert result == {"entity_groups": [], "terms": []}

    @pytest.mark.asyncio
    async def test_collapses_whitespace_in_terms(self):
        payload = json.dumps({"groups": [{"term": "  non\n\tsmall   cell  ", "synonyms": [], "category": ""}]})
        with _complete_returning(payload):
            result = await OllamaConnector.generate_search_terms("question")
        assert result["entity_groups"][0]["term"] == "non small cell"

    @pytest.mark.asyncio
    async def test_empty_question_returns_empty_without_calling_llm(self):
        with patch.object(OllamaConnector, "complete", new=AsyncMock()) as mock_complete:
            result = await OllamaConnector.generate_search_terms("   ")
        mock_complete.assert_not_called()
        assert result == {"entity_groups": [], "terms": []}

    @pytest.mark.asyncio
    async def test_none_from_llm_returns_empty(self):
        with _complete_returning(None):
            result = await OllamaConnector.generate_search_terms("some question")
        assert result == {"entity_groups": [], "terms": []}

    @pytest.mark.asyncio
    async def test_unparseable_json_returns_empty(self):
        with _complete_returning("sorry, I cannot do that"):
            result = await OllamaConnector.generate_search_terms("some question")
        assert result == {"entity_groups": [], "terms": []}

    @pytest.mark.asyncio
    async def test_groups_not_a_list_returns_empty(self):
        with _complete_returning(json.dumps({"groups": "glioblastoma"})):
            result = await OllamaConnector.generate_search_terms("brain cancer")
        assert result == {"entity_groups": [], "terms": []}


class TestGenerateSearchTermGroupsFallback:
    @pytest.mark.asyncio
    async def test_uses_llm_result_when_present(self):
        llm_result = {
            "entity_groups": [{"term": "pembrolizumab", "synonyms": ["Keytruda"], "category": "melanoma"}],
            "terms": ["pembrolizumab", "Keytruda"],
        }
        with patch.object(OllamaConnector, "generate_search_terms", new=AsyncMock(return_value=llm_result)):
            with patch(
                "src.routers.conversation_helper._extract_term_groups_from_message",
                new=AsyncMock(),
            ) as mock_nlp:
                terms, groups = await _generate_search_term_groups("immunotherapy for melanoma")
        mock_nlp.assert_not_called()
        assert terms == ["pembrolizumab", "Keytruda"]
        assert groups == llm_result["entity_groups"]

    @pytest.mark.asyncio
    async def test_falls_back_to_nlp_when_llm_empty(self):
        empty = {"entity_groups": [], "terms": []}
        nlp_return = (["glioma"], [{"term": "glioma", "synonyms": [], "category": "brain cancer"}])
        with patch.object(OllamaConnector, "generate_search_terms", new=AsyncMock(return_value=empty)):
            with patch(
                "src.routers.conversation_helper._extract_term_groups_from_message",
                new=AsyncMock(return_value=nlp_return),
            ) as mock_nlp:
                terms, groups = await _generate_search_term_groups("brain tumor")
        mock_nlp.assert_awaited_once()
        assert terms == ["glioma"]
        assert groups == nlp_return[1]

    @pytest.mark.asyncio
    async def test_falls_back_to_nlp_when_llm_raises(self):
        nlp_return = (["sarcoma"], [{"term": "sarcoma", "synonyms": [], "category": "sarcoma"}])
        with patch.object(OllamaConnector, "generate_search_terms", new=AsyncMock(side_effect=RuntimeError("boom"))):
            with patch(
                "src.routers.conversation_helper._extract_term_groups_from_message",
                new=AsyncMock(return_value=nlp_return),
            ) as mock_nlp:
                terms, groups = await _generate_search_term_groups("bone cancer")
        mock_nlp.assert_awaited_once()
        assert terms == ["sarcoma"]


class TestSearchTermsProvider:
    def test_defaults_to_llm(self, monkeypatch):
        monkeypatch.delenv("SEARCH_TERMS_PROVIDER", raising=False)
        assert _search_terms_provider() == "llm"

    def test_respects_nlp(self, monkeypatch):
        monkeypatch.setenv("SEARCH_TERMS_PROVIDER", "NLP")
        assert _search_terms_provider() == "nlp"

    def test_unknown_value_falls_back_to_llm(self, monkeypatch):
        monkeypatch.setenv("SEARCH_TERMS_PROVIDER", "banana")
        assert _search_terms_provider() == "llm"


class TestKindGatesCategoryInBooleanQuery:
    """A disease group's category legitimately widens its OR clause (GBM also
    matching "brain cancer"). A drug's category is the area it's being asked
    about — folding that in as an alternative would let a paper satisfy the
    drug clause without naming the drug, collapsing the AND-of-OR-groups
    query back into exactly what it exists to prevent."""

    def test_condition_category_widens_its_clause(self):
        groups = [
            {"term": "glioblastoma", "synonyms": ["GBM"], "kind": "condition", "category": "brain cancer"},
            {"term": "mebendazole", "synonyms": [], "kind": "drug", "category": ""},
        ]
        and_query, _ = _build_boolean_term_query(["glioblastoma", "GBM", "mebendazole"], groups)
        assert "(brain cancer)" in and_query
        assert and_query == "((glioblastoma) OR (GBM) OR (brain cancer)) AND ((mebendazole))"

    def test_drug_category_does_not_widen_its_clause(self):
        groups = [
            {"term": "triple negative breast cancer", "synonyms": ["TNBC"], "kind": "condition", "category": "breast cancer"},
            {"term": "pembrolizumab", "synonyms": ["Keytruda"], "kind": "drug", "category": "breast cancer"},
        ]
        and_query, _ = _build_boolean_term_query(["pembrolizumab"], groups)
        # The drug clause must still require the drug itself.
        assert and_query.endswith("AND ((pembrolizumab) OR (Keytruda))")
        # The condition clause still gets widened.
        assert and_query.startswith("((triple negative breast cancer) OR (TNBC) OR (breast cancer))")

    def test_biomarker_category_does_not_widen_its_clause(self):
        groups = [
            {"term": "lung adenocarcinoma", "synonyms": [], "kind": "condition", "category": "lung cancer"},
            {"term": "EGFR", "synonyms": ["ERBB1"], "kind": "biomarker", "category": "lung cancer"},
        ]
        and_query, _ = _build_boolean_term_query(["EGFR"], groups)
        assert and_query.endswith("AND ((EGFR) OR (ERBB1))")

    def test_group_without_kind_keeps_legacy_condition_behaviour(self):
        """NLP groups carry no `kind`; their category has always widened the
        clause, and that must not change."""
        groups = [
            {"term": "GBM", "synonyms": ["glioblastoma"], "category": "brain cancer"},
            {"term": "Mebendazole", "synonyms": [], "category": ""},
        ]
        and_query, _ = _build_boolean_term_query(["GBM"], groups)
        assert and_query == "((GBM) OR (glioblastoma) OR (brain cancer)) AND ((Mebendazole))"


class TestGenerateSearchTermsTemperature:
    @pytest.mark.asyncio
    async def test_pins_temperature_to_zero(self):
        """At the provider default temperature the model sampled unrelated
        drugs into a concept's synonym list (observed: "lamivudine" as a
        synonym of pembrolizumab). A wrong synonym inside an OR group makes
        papers about the wrong drug satisfy that clause, so this call must
        stay deterministic."""
        payload = json.dumps({"groups": [{"term": "melanoma", "synonyms": [], "kind": "condition", "category": "melanoma"}]})
        with patch.object(OllamaConnector, "complete", new=AsyncMock(return_value=payload)) as mock_complete:
            await OllamaConnector.generate_search_terms("skin cancer")
        assert mock_complete.await_args.kwargs["temperature"] == 0

    @pytest.mark.asyncio
    async def test_complete_omits_temperature_by_default(self):
        """Other callers (query rewrite, titles, classification) must keep the
        provider default — this param is additive."""
        import inspect
        sig = inspect.signature(OllamaConnector.complete)
        assert sig.parameters["temperature"].default is None


class TestGenerateSearchTermsKind:
    @pytest.mark.asyncio
    async def test_kind_is_parsed_and_normalised(self):
        payload = json.dumps({
            "groups": [
                {"term": "pembrolizumab", "synonyms": [], "kind": "DRUG", "category": "breast cancer"},
                {"term": "PD-L1", "synonyms": [], "kind": "biomarker", "category": ""},
            ]
        })
        with _complete_returning(payload):
            result = await OllamaConnector.generate_search_terms("keytruda for TNBC")
        assert [g["kind"] for g in result["entity_groups"]] == ["drug", "biomarker"]

    @pytest.mark.asyncio
    async def test_missing_or_unknown_kind_defaults_to_condition(self):
        payload = json.dumps({
            "groups": [
                {"term": "glioblastoma", "synonyms": [], "category": "brain cancer"},
                {"term": "osteosarcoma", "synonyms": [], "kind": "nonsense", "category": "bone cancer"},
            ]
        })
        with _complete_returning(payload):
            result = await OllamaConnector.generate_search_terms("question")
        assert [g["kind"] for g in result["entity_groups"]] == ["condition", "condition"]

    @pytest.mark.asyncio
    async def test_kind_survives_the_merge(self):
        merged = _merge_entity_groups([[
            {"term": "pembrolizumab", "synonyms": [], "kind": "drug", "category": "breast cancer"},
        ]])
        assert merged[0]["kind"] == "drug"


class TestMergeEntityGroupsPreservesCategory:
    def test_single_group_keeps_category(self):
        merged = _merge_entity_groups([[{"term": "glioblastoma", "synonyms": ["GBM"], "category": "brain cancer"}]])
        assert merged == [{"term": "glioblastoma", "synonyms": ["GBM"], "category": "brain cancer"}]

    def test_merge_fills_empty_category_from_later_group(self):
        merged = _merge_entity_groups([
            [{"term": "glioma", "synonyms": ["astrocytoma"], "category": ""}],
            [{"term": "Glioma", "synonyms": ["GBM"], "category": "brain cancer"}],
        ])
        assert len(merged) == 1
        assert merged[0]["category"] == "brain cancer"
        assert merged[0]["synonyms"] == ["astrocytoma", "GBM"]
