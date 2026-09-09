"""Tests for the daily/weekly admin digest cron jobs (src/jobs/admin_digest.py)."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock

from src.db.models import SearchAnalytic, BugReport
from src.db.repositories.conversations import create_conversation
from src.db.repositories.messeges import add_message
from src.db.repositories.waitlist import create_waitlist_entry
from src.jobs.admin_digest import (
    _gather_db_stats,
    _gather_axiom_stats,
    _render_axiom_section,
    _table_rows,
    daily_admin_digest,
    weekly_admin_digest,
)


class TestGatherDbStats:
    def test_counts_only_rows_since_cutoff(self, db_session, test_user):
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        old = datetime.now(timezone.utc) - timedelta(hours=2)

        conv = create_conversation(db_session, user_id=test_user.id, title="Recent")
        add_message(db_session, conversation_id=conv.id, role="user", content="hi")

        old_conv = create_conversation(db_session, user_id=test_user.id, title="Old")
        old_conv.created_at = old
        db_session.commit()

        stats = _gather_db_stats(db_session, since)
        assert stats["new_conversations"] == 1

    def test_messages_sent_counts_user_role_only(self, db_session, test_user):
        conv = create_conversation(db_session, user_id=test_user.id, title="Fresh")
        add_message(db_session, conversation_id=conv.id, role="user", content="q1")
        add_message(db_session, conversation_id=conv.id, role="assistant", content="a1")

        since = datetime.now(timezone.utc) - timedelta(hours=1)
        stats = _gather_db_stats(db_session, since)
        assert stats["messages_sent"] == 1

    def test_fallback_triggered_counted(self, db_session, test_conversation):
        db_session.add(SearchAnalytic(
            conversation_id=test_conversation.id, search_query="q", fallback_triggered=1,
        ))
        db_session.add(SearchAnalytic(
            conversation_id=test_conversation.id, search_query="q2", fallback_triggered=0,
        ))
        db_session.commit()

        since = datetime.now(timezone.utc) - timedelta(hours=1)
        stats = _gather_db_stats(db_session, since)
        assert stats["fallback_triggered"] == 1

    def test_waitlist_joined_counted(self, db_session):
        create_waitlist_entry(db_session, "digest-e2e@example.com", "Digest Test")

        since = datetime.now(timezone.utc) - timedelta(hours=1)
        stats = _gather_db_stats(db_session, since)
        assert stats["waitlist_joined"] == 1

    def test_bug_reports_counted(self, db_session, test_user):
        db_session.add(BugReport(user_id=test_user.id, title="Something broke"))
        db_session.commit()

        since = datetime.now(timezone.utc) - timedelta(hours=1)
        stats = _gather_db_stats(db_session, since)
        assert stats["bug_reports"] == 1
        assert stats["feedback"] == 0

    def test_feedback_counted_separately_from_bug_reports(self, db_session, test_user):
        db_session.add(BugReport(user_id=test_user.id, title="Something broke", report_type="bug"))
        db_session.add(BugReport(user_id=test_user.id, title="Love the app", report_type="feedback"))
        db_session.commit()

        since = datetime.now(timezone.utc) - timedelta(hours=1)
        stats = _gather_db_stats(db_session, since)
        assert stats["bug_reports"] == 1
        assert stats["feedback"] == 1


class TestGatherAxiomStats:
    def test_not_configured_returns_none(self, monkeypatch):
        monkeypatch.delenv("AXIOM_TOKEN_READ", raising=False)
        monkeypatch.delenv("AXIOM_DATASET", raising=False)
        assert _gather_axiom_stats() is None

    def test_query_failure_returns_none(self, monkeypatch):
        monkeypatch.setenv("AXIOM_TOKEN_READ", "fake-token")
        monkeypatch.setenv("AXIOM_DATASET", "fake-dataset")
        with patch("axiom_py.Client") as mock_client_cls:
            mock_client_cls.return_value.apl_query.side_effect = RuntimeError("boom")
            assert _gather_axiom_stats() is None

    def test_successful_query_parsed(self, monkeypatch):
        monkeypatch.setenv("AXIOM_TOKEN_READ", "fake-token")
        monkeypatch.setenv("AXIOM_DATASET", "fake-dataset")

        by_level_field = MagicMock(name="levelname")
        by_level_field.name = "levelname"
        count_field = MagicMock(name="count")
        count_field.name = "count"
        by_level_table = MagicMock(fields=[by_level_field, count_field], columns=[["ERROR", "INFO"], [2, 40]])
        by_level_result = MagicMock(tables=[by_level_table])

        msg_field = MagicMock()
        msg_field.name = "msg"
        top_errors_table = MagicMock(fields=[msg_field, count_field], columns=[["boom"], [2]])
        top_errors_result = MagicMock(tables=[top_errors_table])

        with patch("axiom_py.Client") as mock_client_cls:
            mock_client_cls.return_value.apl_query.side_effect = [by_level_result, top_errors_result]
            stats = _gather_axiom_stats()

        assert stats["by_level"] == {"ERROR": 2, "INFO": 40}
        assert stats["top_errors"] == [{"msg": "boom", "count": 2}]


class TestTableRows:
    def test_zips_fields_and_columns(self):
        f1, f2 = MagicMock(), MagicMock()
        f1.name, f2.name = "a", "b"
        table = MagicMock(fields=[f1, f2], columns=[[1, 2], ["x", "y"]])
        assert _table_rows(table) == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]

    def test_empty_columns(self):
        table = MagicMock(fields=[], columns=[])
        assert _table_rows(table) == []


class TestRenderAxiomSection:
    def test_none_shows_unavailable(self):
        html = _render_axiom_section(None)
        assert "not configured" in html.lower() or "unavailable" in html.lower() or "failed" in html.lower()

    def test_empty_by_level_shows_no_activity(self):
        html = _render_axiom_section({"by_level": {}, "top_errors": []})
        assert "No log activity" in html

    def test_populated_stats_render(self):
        html = _render_axiom_section({"by_level": {"ERROR": 3}, "top_errors": [{"msg": "boom", "count": 3}]})
        assert "ERROR" in html
        assert "3" in html
        assert "boom" in html
        assert "Top errors" in html


class TestDailyAdminDigestJob:
    @pytest.mark.asyncio
    async def test_sends_with_gathered_stats(self, db_session, test_user):
        captured = {}

        async def fake_send(template_data):
            captured.update(template_data)
            return 1

        with patch("src.jobs.admin_digest.SessionLocal", return_value=db_session), \
             patch("src.jobs.admin_digest._gather_axiom_stats", return_value=None), \
             patch("src.jobs.admin_digest.send_daily_admin_digest_email", new=fake_send):
            await daily_admin_digest(ctx={})

        assert "new_users" in captured
        assert "axiom_section" in captured
        assert "date" in captured

    @pytest.mark.asyncio
    async def test_closes_db_session(self, db_session):
        db_session.close = MagicMock(wraps=db_session.close)
        with patch("src.jobs.admin_digest.SessionLocal", return_value=db_session), \
             patch("src.jobs.admin_digest._gather_axiom_stats", return_value=None), \
             patch("src.jobs.admin_digest.send_daily_admin_digest_email", new=AsyncMock(return_value=0)):
            await daily_admin_digest(ctx={})
        db_session.close.assert_called_once()


class TestWeeklyAdminDigestJob:
    @pytest.mark.asyncio
    async def test_sends_with_gathered_stats_and_total_users(self, db_session, test_user):
        captured = {}

        async def fake_send(template_data):
            captured.update(template_data)
            return 1

        with patch("src.jobs.admin_digest.SessionLocal", return_value=db_session), \
             patch("src.jobs.admin_digest.send_weekly_admin_digest_email", new=fake_send):
            await weekly_admin_digest(ctx={})

        assert captured["total_users"] >= 1
        assert "new_users" in captured
        assert "axiom_section" not in captured
