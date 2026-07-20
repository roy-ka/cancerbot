"""Tests for entity-group-aware search query construction.

Covers the fix for a heavily-synonymed entity (e.g. 5 GBM synonyms) drowning
out a single-term entity (e.g. one drug name) in PubMed/CrossRef/Wikipedia
search queries built from a flat extracted-terms list.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from src.routers.conversation_helper import (
    _merge_entity_groups,
    _representative_terms,
    _search_pubmed_sources,
    _search_crossref_sources,
)


def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
    return resp


# ---------------------------------------------------------------------------
# _merge_entity_groups
# ---------------------------------------------------------------------------

class TestMergeEntityGroups:
    def test_merges_synonyms_across_messages_case_insensitively(self):
        groups_per_message = [
            [{"term": "GBM", "synonyms": ["glioblastoma", "glioblastoma multiforme"]}],
            [{"term": "gbm", "synonyms": ["glioblastoma", "high-grade glioma"]}],
        ]
        merged = _merge_entity_groups(groups_per_message)
        assert len(merged) == 1
        assert merged[0]["term"] == "GBM"
        assert set(merged[0]["synonyms"]) == {"glioblastoma", "glioblastoma multiforme", "high-grade glioma"}

    def test_keeps_distinct_entities_separate(self):
        groups_per_message = [
            [
                {"term": "Mebendazole", "synonyms": []},
                {"term": "GBM", "synonyms": ["glioblastoma"]},
            ]
        ]
        merged = _merge_entity_groups(groups_per_message)
        terms = {g["term"] for g in merged}
        assert terms == {"Mebendazole", "GBM"}

    def test_empty_input_returns_empty_list(self):
        assert _merge_entity_groups([]) == []
        assert _merge_entity_groups([[]]) == []


# ---------------------------------------------------------------------------
# _representative_terms
# ---------------------------------------------------------------------------

class TestRepresentativeTerms:
    def test_falls_back_to_flat_terms_when_no_groups(self):
        fallback = ["Mebendazole", "GBM", "glioblastoma"]
        assert _representative_terms([], fallback) == fallback
        assert _representative_terms(None, fallback) == fallback

    def test_returns_one_term_per_group_ignoring_synonyms(self):
        groups = [
            {"term": "Mebendazole", "synonyms": []},
            {"term": "GBM", "synonyms": ["glioblastoma", "glioblastoma multiforme", "grade IV glioma", "high-grade glioma"]},
        ]
        result = _representative_terms(groups, ["fallback"])
        assert result == ["Mebendazole", "GBM"]


# ---------------------------------------------------------------------------
# _search_pubmed_sources — AND-of-groups query with fallback
# ---------------------------------------------------------------------------

class TestPubmedEntityGroupQuery:
    @pytest.mark.asyncio
    async def test_uses_and_query_when_entity_groups_given(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        # AND-grouped query returns a hit — efetch returns no articles (empty XML) is fine,
        # we only assert on the esearch query string used.
        client.get.side_effect = [
            _mock_response(200, json_data={"esearchresult": {"idlist": ["123"]}}),
            _mock_response(200, text="<PubmedArticleSet></PubmedArticleSet>"),
        ]
        entity_groups = [
            {"term": "Mebendazole", "synonyms": []},
            {"term": "GBM", "synonyms": ["glioblastoma", "glioblastoma multiforme"]},
        ]
        terms = ["Mebendazole", "GBM", "glioblastoma", "glioblastoma multiforme"]
        await _search_pubmed_sources(client, terms, max_results=4, entity_groups=entity_groups)

        first_call_url = client.get.call_args_list[0].args[0]
        assert "AND" in first_call_url or "%20AND%20" in first_call_url

    @pytest.mark.asyncio
    async def test_falls_back_to_flat_or_query_when_and_query_returns_nothing(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [
            _mock_response(200, json_data={"esearchresult": {"idlist": []}}),  # AND query — nothing
            _mock_response(200, json_data={"esearchresult": {"idlist": ["456"]}}),  # flat OR query — hit
            _mock_response(200, text="<PubmedArticleSet></PubmedArticleSet>"),  # efetch
        ]
        entity_groups = [
            {"term": "Mebendazole", "synonyms": []},
            {"term": "GBM", "synonyms": ["glioblastoma"]},
        ]
        terms = ["Mebendazole", "GBM", "glioblastoma"]
        await _search_pubmed_sources(client, terms, max_results=4, entity_groups=entity_groups)

        assert client.get.call_count == 3
        second_call_url = client.get.call_args_list[1].args[0]
        assert "AND" not in second_call_url and "%20AND%20" not in second_call_url

    @pytest.mark.asyncio
    async def test_single_entity_group_skips_and_query(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [
            _mock_response(200, json_data={"esearchresult": {"idlist": []}}),
        ]
        entity_groups = [{"term": "GBM", "synonyms": ["glioblastoma"]}]
        terms = ["GBM", "glioblastoma"]
        result = await _search_pubmed_sources(client, terms, max_results=4, entity_groups=entity_groups)

        assert result == []
        assert client.get.call_count == 1  # only the flat query, no AND attempt


# ---------------------------------------------------------------------------
# _search_crossref_sources — representative-term query
# ---------------------------------------------------------------------------

class TestCrossrefEntityGroupQuery:
    @pytest.mark.asyncio
    async def test_query_uses_one_term_per_entity_not_all_synonyms(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response(200, json_data={"message": {"items": []}})
        entity_groups = [
            {"term": "Mebendazole", "synonyms": []},
            {"term": "GBM", "synonyms": ["glioblastoma", "glioblastoma multiforme", "grade IV glioma", "high-grade glioma"]},
        ]
        terms = ["Mebendazole", "GBM", "glioblastoma", "glioblastoma multiforme", "grade IV glioma", "high-grade glioma"]
        await _search_crossref_sources(client, terms, max_results=4, entity_groups=entity_groups)

        _, kwargs = client.get.call_args
        query = kwargs["params"]["query.bibliographic"]
        assert query == "Mebendazole GBM"
