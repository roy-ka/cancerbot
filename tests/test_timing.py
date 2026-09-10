"""Tests for src/utils/timing.py — the per-stage timing helper used to log
generate-answer flow durations to Axiom (via the standard logging handler)."""
import logging
from unittest.mock import patch
import pytest

from src.utils.timing import timed_stage


class TestTimedStage:
    @pytest.mark.asyncio
    async def test_logs_stage_and_took_ms_on_success(self, caplog):
        with caplog.at_level(logging.INFO, logger="src.utils.timing"):
            async with timed_stage("do_thing", conversation_id="c1"):
                pass

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.stage == "do_thing"
        assert isinstance(record.took_ms, int)
        assert record.took_ms >= 0
        assert record.conversation_id == "c1"

    @pytest.mark.asyncio
    async def test_logs_even_when_the_body_raises(self, caplog):
        with caplog.at_level(logging.INFO, logger="src.utils.timing"):
            with pytest.raises(ValueError):
                async with timed_stage("do_thing"):
                    raise ValueError("boom")

        assert len(caplog.records) == 1
        assert caplog.records[0].stage == "do_thing"

    @pytest.mark.asyncio
    async def test_does_not_swallow_the_exception(self):
        with pytest.raises(RuntimeError, match="boom"):
            async with timed_stage("do_thing"):
                raise RuntimeError("boom")

    @pytest.mark.asyncio
    async def test_extra_kwargs_become_record_fields(self, caplog):
        with caplog.at_level(logging.INFO, logger="src.utils.timing"):
            async with timed_stage("search_pubmed", terms_count=3):
                pass

        record = caplog.records[0]
        assert record.terms_count == 3


async def _fake_search_and_embed(*args, **kwargs):
    return {"terms": [], "latest_terms": [], "indexed": 0, "skipped": 0}


async def _fake_stream_text(*args, **kwargs):
    yield "Glycolysis is a metabolic pathway."
    yield {}  # alias_to_id sentinel, same contract as OllamaConnector.stream_text


class TestGenerateAnswerFlowIsTimed:
    """Confirms the [timing] stages in conversations.py's real request path
    actually fire. search_and_embed/stream_text/run_retrieval are mocked
    here (own patches, not reused from test_conversations.py's file-scoped
    autouse fixture) so this stays a fast, isolated check of conversations.py's
    wraps — conversation_helper.py's internal ones are exercised directly by
    test_entity_grouping.py and test_resource_optimizations.py instead."""

    @patch("src.routers.conversations.OllamaConnector.stream_text", new=_fake_stream_text)
    @patch("src.routers.conversations.search_and_embed", new=_fake_search_and_embed)
    @patch("src.routers.conversations.run_retrieval")
    def test_add_message_logs_a_timing_record_per_stage(self, mock_retrieval, client, test_conversation, caplog):
        mock_retrieval.return_value = {"generation_context": "glycolysis info", "sources_ids": []}

        with caplog.at_level(logging.INFO, logger="src.utils.timing"):
            response = client.post(
                f"/conversations/{test_conversation.id}/add_message",
                json={"content": "What is glycolysis?"},
            )
        assert response.status_code == 200

        stages = {r.stage for r in caplog.records if hasattr(r, "stage")}
        # test_conversation already has one message, so this isn't the first
        # message in it and generate_title doesn't fire — see conftest.py.
        assert stages == {
            "load_conversation",
            "save_user_message",
            "search_and_embed",
            "retrieve_context",
            "generate_answer",
            "save_assistant_message",
            "total_message",
        }
