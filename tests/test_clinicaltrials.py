"""Tests for the ClinicalTrials.gov evidence source (completed trials).

Covers the v2 record → source conversion, the search function's query
building / COMPLETED filter / fallback, the shared boolean-query builder, and
the nct: stable-id branch.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

import httpx

from src.routers.conversation_helper import (
    _build_boolean_term_query,
    _clinicaltrial_to_source,
    _search_clinicaltrials_sources,
    _stable_source_id,
)


def _study(nct="NCT01729260", *, brief_title="Mebendazole in High-Grade Glioma",
           summary="A study of mebendazole in newly diagnosed high-grade glioma patients.",
           conditions=("High-Grade Glioma",), interventions=("Mebendazole",),
           phases=("PHASE1",), status="COMPLETED", completion="2021-06-01",
           has_results=False):
    ps = {
        "identificationModule": {"nctId": nct, "briefTitle": brief_title},
        "descriptionModule": {"briefSummary": summary},
        "conditionsModule": {"conditions": list(conditions)},
        "armsInterventionsModule": {"interventions": [{"name": i} for i in interventions]},
        "designModule": {"phases": list(phases)},
        "statusModule": {
            "overallStatus": status,
            "completionDateStruct": {"date": completion} if completion else {},
        },
    }
    return {"protocolSection": ps, "hasResults": has_results}


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


class TestBuildBooleanTermQuery:
    def test_flat_query_is_or_of_terms(self):
        and_q, flat_q = _build_boolean_term_query(["a", "b", "c"])
        assert flat_q == "(a) OR (b) OR (c)"
        assert and_q is None

    def test_and_query_when_two_entity_groups(self):
        groups = [
            {"term": "Mebendazole", "synonyms": []},
            {"term": "GBM", "synonyms": ["glioblastoma"]},
        ]
        and_q, _ = _build_boolean_term_query(["Mebendazole", "GBM", "glioblastoma"], groups)
        assert and_q == "((Mebendazole)) AND ((GBM) OR (glioblastoma))"

    def test_category_appended_to_group(self):
        groups = [
            {"term": "Mebendazole", "synonyms": []},
            {"term": "GBM", "synonyms": ["glioblastoma"], "category": "brain cancer"},
        ]
        and_q, _ = _build_boolean_term_query(["Mebendazole", "GBM"], groups)
        assert "brain cancer" in and_q

    def test_single_group_yields_no_and_query(self):
        and_q, _ = _build_boolean_term_query(["GBM"], [{"term": "GBM", "synonyms": []}])
        assert and_q is None


class TestClinicalTrialToSource:
    def test_maps_core_fields(self):
        s = _clinicaltrial_to_source(_study())
        assert s["source_type"] == "clinicaltrials"
        assert s["nct"] == "NCT01729260"
        assert s["url"] == "https://clinicaltrials.gov/study/NCT01729260"
        assert s["year"] == 2021
        assert s["tags"] == ["clinical_trial"]

    def test_content_includes_structured_facts(self):
        content = _clinicaltrial_to_source(_study())["content_for_embedding"]
        assert "Conditions: High-Grade Glioma" in content
        assert "Interventions: Mebendazole" in content
        assert "Phase: PHASE1" in content
        assert "Status: COMPLETED" in content

    def test_completed_with_results_is_evidence_level_clinical_trial(self):
        s = _clinicaltrial_to_source(_study(has_results=True))
        assert s["pub_types"] == ["clinical trial"]

    def test_completed_without_results_left_at_default(self):
        s = _clinicaltrial_to_source(_study(has_results=False))
        assert s["pub_types"] is None

    def test_year_falls_back_across_date_fields(self):
        study = _study(completion=None)
        study["protocolSection"]["statusModule"]["startDateStruct"] = {"date": "2015-03"}
        assert _clinicaltrial_to_source(study)["year"] == 2015

    def test_no_nct_returns_none(self):
        study = _study()
        study["protocolSection"]["identificationModule"]["nctId"] = ""
        assert _clinicaltrial_to_source(study) is None

    def test_no_descriptive_text_returns_none(self):
        study = _study(brief_title="", summary="", conditions=(), interventions=(), phases=(), status="")
        assert _clinicaltrial_to_source(study) is None


class TestSearchClinicalTrials:
    @pytest.mark.asyncio
    async def test_empty_terms_returns_empty(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        assert await _search_clinicaltrials_sources(client, []) == []
        client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_filters_to_completed_status(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response(200, {"studies": [_study()]})
        await _search_clinicaltrials_sources(client, ["glioblastoma"])

        _, kwargs = client.get.call_args
        assert kwargs["params"]["filter.overallStatus"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_uses_and_query_then_falls_back_to_flat(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [
            _mock_response(200, {"studies": []}),          # AND query — nothing
            _mock_response(200, {"studies": [_study()]}),  # flat OR — hit
        ]
        groups = [
            {"term": "Mebendazole", "synonyms": []},
            {"term": "GBM", "synonyms": ["glioblastoma"]},
        ]
        out = await _search_clinicaltrials_sources(
            client, ["Mebendazole", "GBM", "glioblastoma"], entity_groups=groups,
        )
        assert client.get.call_count == 2
        first_term = client.get.call_args_list[0].kwargs["params"]["query.term"]
        second_term = client.get.call_args_list[1].kwargs["params"]["query.term"]
        assert "AND" in first_term
        assert "AND" not in second_term
        assert len(out) == 1

    @pytest.mark.asyncio
    async def test_request_failure_returns_empty(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = httpx.TimeoutException("timeout")
        assert await _search_clinicaltrials_sources(client, ["cancer"]) == []

    @pytest.mark.asyncio
    async def test_respects_max_results(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        studies = [_study(nct=f"NCT{i:08d}") for i in range(10)]
        client.get.return_value = _mock_response(200, {"studies": studies})
        out = await _search_clinicaltrials_sources(client, ["cancer"], max_results=3)
        assert len(out) == 3


class TestClinicalTrialIndexing:
    def test_indexes_with_nct_id_and_field(self):
        from unittest.mock import patch
        from src.routers.conversation_helper import _embed_and_index_sources

        source = _clinicaltrial_to_source(_study())
        # pad the summary so it clears the MIN_FULLTEXT_WORDS floor
        source["content_for_embedding"] += " " + " ".join(["glioblastoma"] * 30)

        fake_db = MagicMock()
        fake_db.existing_base_source_ids.return_value = set()
        fake_db.bulk_index_to_db.side_effect = lambda index_name, docs: (len(list(docs)), [])
        with patch("src.routers.conversation_helper.dbConnector", return_value=fake_db), \
             patch("src.routers.conversation_helper.EmbeddingConnector.embed_texts",
                   side_effect=lambda texts: [[0.1] * 768 for _ in texts]):
            _embed_and_index_sources([source], terms=["glioblastoma"])

        docs = [d for c in fake_db.bulk_index_to_db.call_args_list for d in c.args[1]]
        assert docs
        for doc in docs:
            assert doc["id"].startswith("nct:NCT01729260")
            assert doc["nct"] == "NCT01729260"
            assert doc["source_type"] == "clinicaltrials"


class TestStableSourceIdNct:
    def test_nct_branch(self):
        assert _stable_source_id({"nct": "NCT01729260"}) == "nct:NCT01729260"

    def test_pmid_still_wins_over_nct(self):
        assert _stable_source_id({"pmid": "123", "nct": "NCT1"}) == "pmid:123"

    def test_nct_wins_over_url(self):
        assert _stable_source_id({"nct": "NCT1", "url": "https://x"}) == "nct:NCT1"
