from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest

from src.db import models
from src.jobs.account_deletion import _sweep_once
from src.auth.security import SecurityUtils


class TestAccountDeletionSweep:
    async def _run(self, db_session):
        with patch("src.jobs.account_deletion.send_account_deleted_email", new=AsyncMock()) as mock_send:
            await _sweep_once(db_session)
        return mock_send

    @pytest.mark.asyncio
    async def test_deletes_users_past_grace_period(self, db_session, test_user):
        test_user.deletion_scheduled_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db_session.commit()

        mock_send = await self._run(db_session)

        db_session.expire_all()
        assert db_session.query(models.User).filter(models.User.id == test_user.id).first() is None
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_leaves_users_within_grace_period_untouched(self, db_session, test_user):
        test_user.deletion_scheduled_at = datetime.now(timezone.utc) + timedelta(days=1)
        db_session.commit()

        mock_send = await self._run(db_session)

        db_session.expire_all()
        assert db_session.query(models.User).filter(models.User.id == test_user.id).first() is not None
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_leaves_users_without_pending_deletion_untouched(self, db_session, test_user):
        mock_send = await self._run(db_session)

        db_session.expire_all()
        assert db_session.query(models.User).filter(models.User.id == test_user.id).first() is not None
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_one_failing_deletion_does_not_block_others_in_the_batch(self, db_session, test_user):
        from src.db.repositories.users import create_user, delete_user as real_delete_user

        other_user = create_user(
            db_session,
            first_name="Other", last_name="User",
            email="other-sweep-target@example.com",
            password_hash=SecurityUtils.hash_password("TestPass123!"),
        )
        other_user.email_verified = True
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        test_user.deletion_scheduled_at = past
        other_user.deletion_scheduled_at = past
        db_session.commit()
        failing_id, other_id = test_user.id, other_user.id

        def flaky_delete_user(db, user_id):
            if user_id == failing_id:
                raise RuntimeError("simulated DB failure")
            return real_delete_user(db=db, user_id=user_id)

        with patch("src.jobs.account_deletion.delete_user", side_effect=flaky_delete_user), \
             patch("src.jobs.account_deletion.send_account_deleted_email", new=AsyncMock()):
            await _sweep_once(db_session)

        db_session.expire_all()
        assert db_session.query(models.User).filter(models.User.id == failing_id).first() is not None
        assert db_session.query(models.User).filter(models.User.id == other_id).first() is None
