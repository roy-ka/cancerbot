from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest

from src.db import models
from src.jobs.account_deletion import (
    delete_scheduled_user_job,
    reschedule_pending_deletions,
    job_id_for_user,
)
from src.auth.security import SecurityUtils


class TestDeleteScheduledUserJob:
    """delete_scheduled_user_job opens its own session (arq jobs don't get
    one injected) — every test here runs it against TestingSessionLocal,
    then re-queries via the fixture's own db_session to observe the result."""

    @pytest.mark.asyncio
    async def test_deletes_user_past_grace_period(self, TestingSessionLocal, db_session, test_user):
        test_user.deletion_scheduled_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db_session.commit()
        user_id = test_user.id

        with patch("src.jobs.account_deletion.SessionLocal", TestingSessionLocal), \
             patch("src.jobs.account_deletion.send_account_deleted_email", new=AsyncMock()) as mock_send:
            await delete_scheduled_user_job({}, user_id=str(user_id))

        db_session.expire_all()
        assert db_session.query(models.User).filter(models.User.id == user_id).first() is None
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_noop_when_deletion_was_cancelled(self, TestingSessionLocal, db_session, test_user):
        # deletion_scheduled_at is None (never scheduled / cancelled) — the
        # job must not delete the user just because it was fired.
        user_id = test_user.id

        with patch("src.jobs.account_deletion.SessionLocal", TestingSessionLocal), \
             patch("src.jobs.account_deletion.send_account_deleted_email", new=AsyncMock()) as mock_send:
            await delete_scheduled_user_job({}, user_id=str(user_id))

        db_session.expire_all()
        assert db_session.query(models.User).filter(models.User.id == user_id).first() is not None
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_rescheduled_to_a_later_date(self, TestingSessionLocal, db_session, test_user):
        """Simulates a stale job firing after cancel-then-reschedule: the
        job that was deferred for the OLD date must not delete the user
        now that deletion_scheduled_at points to a future date instead."""
        test_user.deletion_scheduled_at = datetime.now(timezone.utc) + timedelta(days=7)
        db_session.commit()
        user_id = test_user.id

        with patch("src.jobs.account_deletion.SessionLocal", TestingSessionLocal), \
             patch("src.jobs.account_deletion.send_account_deleted_email", new=AsyncMock()) as mock_send:
            await delete_scheduled_user_job({}, user_id=str(user_id))

        db_session.expire_all()
        assert db_session.query(models.User).filter(models.User.id == user_id).first() is not None
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_user_already_gone(self, TestingSessionLocal):
        import uuid
        with patch("src.jobs.account_deletion.SessionLocal", TestingSessionLocal), \
             patch("src.jobs.account_deletion.send_account_deleted_email", new=AsyncMock()) as mock_send:
            await delete_scheduled_user_job({}, user_id=str(uuid.uuid4()))  # must not raise
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_failure_is_logged_not_raised(self, TestingSessionLocal, db_session, test_user):
        test_user.deletion_scheduled_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db_session.commit()
        user_id = test_user.id

        with patch("src.jobs.account_deletion.SessionLocal", TestingSessionLocal), \
             patch("src.jobs.account_deletion.delete_user", side_effect=RuntimeError("boom")), \
             patch("src.jobs.account_deletion.send_account_deleted_email", new=AsyncMock()) as mock_send:
            await delete_scheduled_user_job({}, user_id=str(user_id))  # must not raise

        mock_send.assert_not_called()
        db_session.expire_all()
        assert db_session.query(models.User).filter(models.User.id == user_id).first() is not None


class TestJobIdForUser:
    def test_deterministic_per_user(self):
        import uuid
        uid = uuid.uuid4()
        assert job_id_for_user(uid) == job_id_for_user(uid)
        assert job_id_for_user(uid) != job_id_for_user(uuid.uuid4())


class TestReschedulePendingDeletions:
    @pytest.mark.asyncio
    async def test_enqueues_a_job_per_pending_user(self, TestingSessionLocal, db_session, test_user):
        test_user.deletion_scheduled_at = datetime.now(timezone.utc) + timedelta(days=3)
        db_session.commit()

        captured = []

        async def fake_enqueue(job_name, **kwargs):
            captured.append((job_name, kwargs))

        with patch("src.jobs.account_deletion.SessionLocal", TestingSessionLocal), \
             patch("src.queue.enqueue", new=fake_enqueue):
            await reschedule_pending_deletions({})

        assert len(captured) == 1
        job_name, kwargs = captured[0]
        assert job_name == "delete_scheduled_user_job"
        assert kwargs["user_id"] == str(test_user.id)
        assert kwargs["_job_id"] == job_id_for_user(test_user.id)
        assert kwargs["_defer_until"] == test_user.deletion_scheduled_at

    @pytest.mark.asyncio
    async def test_noop_when_nobody_pending(self, TestingSessionLocal):
        captured = []

        async def fake_enqueue(job_name, **kwargs):
            captured.append((job_name, kwargs))

        with patch("src.jobs.account_deletion.SessionLocal", TestingSessionLocal), \
             patch("src.queue.enqueue", new=fake_enqueue):
            await reschedule_pending_deletions({})

        assert captured == []
