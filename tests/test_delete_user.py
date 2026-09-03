import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

from src.db import models
from src.db.repositories.tokens import create_deletion_request_token
from src.auth.security import SecurityUtils


def _request_delete(client):
    return client.post("/auth/request-delete/")


def _confirm_delete(client, token: str, password: str):
    return client.post("/auth/confirm-delete/", json={"token": token, "password": password})


class TestRequestDelete:
    def test_success_sends_email_and_creates_token(self, client, test_user, db_session):
        with patch("src.routers.auth.enqueue", new=AsyncMock()) as mock_send:
            response = _request_delete(client)
        assert response.status_code == 200
        assert response.json()["ok"] is True
        mock_send.assert_called_once()

        db_session.expire_all()
        tokens = db_session.query(models.Token).filter(
            models.Token.user_id == test_user.id,
            models.Token.token_type == "account_deletion",
        ).all()
        assert len(tokens) == 1

    def test_non_prod_response_includes_token_for_automation(self, client):
        """ENV != production exposes the raw token, mirroring register's verification_token —
        needed since there's no inbox to read the emailed link from in tests/CI."""
        with patch("src.routers.auth.enqueue", new=AsyncMock()):
            response = _request_delete(client)
        assert response.json()["deletion_token"]

    def test_unauthenticated_returns_401(self, anon_client):
        response = anon_client.post("/auth/request-delete/")
        assert response.status_code == 401

    def test_rate_limited_after_max_attempts(self, client, test_user, db_session):
        from src.db.repositories.rate_limit import MAX_REQUEST_DELETE_ATTEMPTS
        with patch("src.routers.auth.enqueue", new=AsyncMock()):
            for _ in range(MAX_REQUEST_DELETE_ATTEMPTS):
                assert _request_delete(client).status_code == 200
            blocked = _request_delete(client)
        assert blocked.status_code == 429
        assert "too many" in blocked.json()["detail"].lower()


class TestConfirmDelete:
    def test_success_schedules_deletion_and_clears_cookie(self, client, test_user, db_session):
        token = create_deletion_request_token(db_session, test_user.id)
        with patch("src.routers.auth.enqueue", new=AsyncMock()):
            response = _confirm_delete(client, token, "TestPass123!")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "deletion_date" in data
        assert "access_token" in response.headers.get("set-cookie", "")

        db_session.expire_all()
        user = db_session.query(models.User).filter(models.User.id == test_user.id).first()
        assert user.deletion_scheduled_at is not None

    def test_success_enqueues_deferred_deletion_job(self, client, test_user, db_session):
        """The actual deletion is a one-shot job deferred to
        deletion_date, not left for a cron sweep to find later — see
        src/jobs/account_deletion.py."""
        from src.jobs.account_deletion import job_id_for_user

        token = create_deletion_request_token(db_session, test_user.id)
        captured = []

        async def fake_enqueue(job_name, **kwargs):
            captured.append((job_name, kwargs))

        with patch("src.routers.auth.enqueue", new=fake_enqueue):
            response = _confirm_delete(client, token, "TestPass123!")

        deletion_job = next(
            (kwargs for name, kwargs in captured if name == "delete_scheduled_user_job"), None
        )
        assert deletion_job is not None
        assert deletion_job["user_id"] == str(test_user.id)
        assert deletion_job["_job_id"] == job_id_for_user(test_user.id)
        assert deletion_job["_defer_until"].isoformat() == response.json()["deletion_date"]

    def test_wrong_password_returns_401_and_keeps_token_usable(self, client, test_user, db_session):
        token = create_deletion_request_token(db_session, test_user.id)
        response = _confirm_delete(client, token, "WrongPassword!")
        assert response.status_code == 401

        # Token must not be burned by a failed password attempt — retry should still work
        db_session.expire_all()
        with patch("src.routers.auth.enqueue", new=AsyncMock()):
            retry = _confirm_delete(client, token, "TestPass123!")
        assert retry.status_code == 200

    def test_token_cannot_be_reused_after_success(self, client, test_user, db_session):
        """A second confirm-delete for the same token must fail, not
        re-schedule deletion or re-enqueue the deferred delete job — this is
        the sequential case of the double-submit race the row lock in
        verify_deletion_token (for_update=True) closes; true concurrent
        requests can't be reproduced against the in-memory sqlite test DB,
        which doesn't honor FOR UPDATE."""
        token = create_deletion_request_token(db_session, test_user.id)
        with patch("src.routers.auth.enqueue", new=AsyncMock()):
            first = _confirm_delete(client, token, "TestPass123!")
        assert first.status_code == 200

        db_session.expire_all()
        with patch("src.routers.auth.enqueue", new=AsyncMock()) as mock_enqueue:
            second = _confirm_delete(client, token, "TestPass123!")
        assert second.status_code == 400
        mock_enqueue.assert_not_called()

    def test_invalid_token_returns_400(self, client):
        response = _confirm_delete(client, "not-a-real-token", "TestPass123!")
        assert response.status_code == 400

    def test_expired_token_returns_400(self, client, test_user, db_session):
        token = create_deletion_request_token(db_session, test_user.id)
        record = db_session.query(models.Token).filter(
            models.Token.user_id == test_user.id,
            models.Token.token_type == "account_deletion",
        ).first()
        record.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()

        response = _confirm_delete(client, token, "TestPass123!")
        assert response.status_code == 400


class TestConfirmDeleteLockout:
    def test_five_wrong_passwords_locks_account(self, client, test_user, db_session):
        token = create_deletion_request_token(db_session, test_user.id)
        for _ in range(5):
            response = _confirm_delete(client, token, "WrongPassword!")
        assert response.status_code == 429

    def test_locked_account_rejects_even_a_fresh_valid_token(self, client, test_user, db_session):
        token = create_deletion_request_token(db_session, test_user.id)
        for _ in range(5):
            _confirm_delete(client, token, "WrongPassword!")

        db_session.expire_all()
        fresh_token = create_deletion_request_token(db_session, test_user.id)
        response = _confirm_delete(client, fresh_token, "TestPass123!")
        assert response.status_code == 429

    def test_lockout_is_shared_with_login(self, client, test_user, db_session):
        """Brute-forcing the password via confirm-delete locks the same LoginAttempt
        row used by /auth/login/ — a deliberate reuse of existing lockout infra."""
        token = create_deletion_request_token(db_session, test_user.id)
        for _ in range(5):
            _confirm_delete(client, token, "WrongPassword!")

        login_response = client.post(
            "/auth/login/",
            json={"email": test_user.email, "password": "TestPass123!", "rememberMe": False},
        )
        assert login_response.status_code == 429


class TestPendingDeletionBlocksAccess:
    def test_login_returns_pending_deletion_with_cancel_token(self, anon_client, test_user, db_session):
        test_user.deletion_scheduled_at = datetime.now(timezone.utc) + timedelta(days=7)
        db_session.commit()

        response = anon_client.post(
            "/auth/login/",
            json={"email": test_user.email, "password": "TestPass123!", "rememberMe": False},
        )
        assert response.status_code == 403
        detail = response.json()["detail"]
        assert detail["code"] == "pending_deletion"
        assert detail["cancel_token"]

    def test_existing_session_rejected_once_deletion_scheduled(self, anon_client, test_user, db_session):
        login_res = anon_client.post(
            "/auth/login/",
            json={"email": test_user.email, "password": "TestPass123!", "rememberMe": False},
        )
        assert login_res.status_code == 200

        test_user.deletion_scheduled_at = datetime.now(timezone.utc) + timedelta(days=7)
        db_session.commit()

        check_res = anon_client.get("/auth/check/")
        assert check_res.status_code == 401


class TestCancelDelete:
    def test_success_clears_pending_deletion(self, anon_client, test_user, db_session):
        test_user.deletion_scheduled_at = datetime.now(timezone.utc) + timedelta(days=7)
        db_session.commit()

        cancel_token = SecurityUtils.create_jwt_token({
            "sub": str(test_user.id),
            "purpose": "cancel_delete",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        })
        response = anon_client.post("/auth/cancel-delete/", json={"cancel_token": cancel_token})
        assert response.status_code == 200

        db_session.expire_all()
        user = db_session.query(models.User).filter(models.User.id == test_user.id).first()
        assert user.deletion_scheduled_at is None

    def test_success_sends_cancellation_email(self, anon_client, test_user, db_session):
        test_user.deletion_scheduled_at = datetime.now(timezone.utc) + timedelta(days=7)
        db_session.commit()

        cancel_token = SecurityUtils.create_jwt_token({
            "sub": str(test_user.id),
            "purpose": "cancel_delete",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        })
        with patch("src.routers.auth.enqueue", new=AsyncMock()) as mock_enqueue:
            response = anon_client.post("/auth/cancel-delete/", json={"cancel_token": cancel_token})
        assert response.status_code == 200
        mock_enqueue.assert_called_once_with(
            "send_delete_account_cancelled_email_job", to=test_user.email, name=test_user.display_name
        )

    def test_wrong_purpose_token_rejected(self, anon_client, test_user):
        bad_token = SecurityUtils.create_jwt_token({
            "sub": str(test_user.id),
            "purpose": "something_else",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        })
        response = anon_client.post("/auth/cancel-delete/", json={"cancel_token": bad_token})
        assert response.status_code == 400
