import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

from src.db import models
from src.db.repositories.tokens import create_deletion_request_token
from src.auth.security import SecurityUtils


def _request_delete(client):
    return client.post("/auth/request-delete/")


def _confirm_delete(client, token: str):
    return client.post("/auth/confirm-delete/", json={"token": token})


def _cancel_token(user, **overrides):
    payload = {
        "sub": str(user.id),
        "purpose": "cancel_delete",
        "tv": user.token_version,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
    }
    payload.update(overrides)
    return SecurityUtils.create_jwt_token(payload)


def _sign_in(client, email):
    """Request a code and enter it, reading the code from the enqueued
    email the way a user reads it from their inbox."""
    codes = {}

    async def fake_enqueue(job_name, **kwargs):
        if job_name == "send_login_code_email_job":
            codes[kwargs["to"]] = kwargs["code"]

    with patch("src.routers.auth.enqueue", new=fake_enqueue):
        client.post("/auth/request-code/", json={"email": email})
    return client.post("/auth/verify-code/", json={"email": email, "code": codes[email], "rememberMe": False})


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
            response = _confirm_delete(client, token)
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
            response = _confirm_delete(client, token)

        deletion_job = next(
            (kwargs for name, kwargs in captured if name == "delete_scheduled_user_job"), None
        )
        assert deletion_job is not None
        assert deletion_job["user_id"] == str(test_user.id)
        assert deletion_job["_job_id"] == job_id_for_user(test_user.id)
        assert deletion_job["_defer_until"].isoformat() == response.json()["deletion_date"]

    def test_no_password_is_required(self, client, test_user, db_session):
        """The emailed link is the proof of inbox control; an old client
        still sending a password field is fine, it's ignored."""
        token = create_deletion_request_token(db_session, test_user.id)
        with patch("src.routers.auth.enqueue", new=AsyncMock()):
            response = client.post("/auth/confirm-delete/", json={"token": token, "password": "anything"})
        assert response.status_code == 200

    def test_token_cannot_be_reused_after_success(self, client, test_user, db_session):
        """A second confirm-delete for the same token must fail, not
        re-schedule deletion or re-enqueue the deferred delete job — this is
        the sequential case of the double-submit race the row lock in
        verify_deletion_token (for_update=True) closes; true concurrent
        requests can't be reproduced against the in-memory sqlite test DB,
        which doesn't honor FOR UPDATE."""
        token = create_deletion_request_token(db_session, test_user.id)
        with patch("src.routers.auth.enqueue", new=AsyncMock()):
            first = _confirm_delete(client, token)
        assert first.status_code == 200

        db_session.expire_all()
        with patch("src.routers.auth.enqueue", new=AsyncMock()) as mock_enqueue:
            second = _confirm_delete(client, token)
        assert second.status_code == 400
        mock_enqueue.assert_not_called()

    def test_invalid_token_returns_400(self, client):
        response = _confirm_delete(client, "not-a-real-token")
        assert response.status_code == 400

    def test_expired_token_returns_400(self, client, test_user, db_session):
        token = create_deletion_request_token(db_session, test_user.id)
        record = db_session.query(models.Token).filter(
            models.Token.user_id == test_user.id,
            models.Token.token_type == "account_deletion",
        ).first()
        record.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()

        response = _confirm_delete(client, token)
        assert response.status_code == 400


class TestPendingDeletionBlocksAccess:
    def test_sign_in_returns_pending_deletion_with_cancel_token(self, anon_client, test_user, db_session):
        test_user.deletion_scheduled_at = datetime.now(timezone.utc) + timedelta(days=7)
        db_session.commit()

        response = _sign_in(anon_client, test_user.email)
        assert response.status_code == 403
        detail = response.json()["detail"]
        assert detail["code"] == "pending_deletion"
        assert detail["cancel_token"]
        assert "access_token" not in anon_client.cookies

    def test_existing_session_rejected_once_deletion_scheduled(self, anon_client, test_user, db_session):
        login_res = _sign_in(anon_client, test_user.email)
        assert login_res.status_code == 200

        test_user.deletion_scheduled_at = datetime.now(timezone.utc) + timedelta(days=7)
        db_session.commit()

        check_res = anon_client.get("/auth/check/")
        assert check_res.status_code == 401


class TestCancelDelete:
    def test_success_clears_pending_deletion(self, anon_client, test_user, db_session):
        test_user.deletion_scheduled_at = datetime.now(timezone.utc) + timedelta(days=7)
        db_session.commit()

        response = anon_client.post("/auth/cancel-delete/", json={"cancel_token": _cancel_token(test_user)})
        assert response.status_code == 200

        db_session.expire_all()
        user = db_session.query(models.User).filter(models.User.id == test_user.id).first()
        assert user.deletion_scheduled_at is None

    def test_success_signs_the_user_in(self, anon_client, test_user, db_session):
        """The code that produced the cancel token is already spent, so
        cancelling must also start the session."""
        test_user.deletion_scheduled_at = datetime.now(timezone.utc) + timedelta(days=7)
        db_session.commit()

        response = anon_client.post("/auth/cancel-delete/", json={"cancel_token": _cancel_token(test_user)})
        assert response.status_code == 200
        assert anon_client.get("/auth/check/").status_code == 200

    def test_full_flow_sign_in_then_cancel(self, anon_client, test_user, db_session):
        test_user.deletion_scheduled_at = datetime.now(timezone.utc) + timedelta(days=7)
        db_session.commit()

        cancel_token = _sign_in(anon_client, test_user.email).json()["detail"]["cancel_token"]
        assert anon_client.post("/auth/cancel-delete/", json={"cancel_token": cancel_token}).status_code == 200
        assert anon_client.get("/auth/check/").status_code == 200

    def test_token_from_before_a_session_revocation_is_rejected(self, anon_client, test_user, db_session):
        cancel_token = _cancel_token(test_user)
        test_user.token_version += 1
        db_session.commit()
        response = anon_client.post("/auth/cancel-delete/", json={"cancel_token": cancel_token})
        assert response.status_code == 400
        assert "access_token" not in anon_client.cookies

    def test_success_sends_cancellation_email(self, anon_client, test_user, db_session):
        test_user.deletion_scheduled_at = datetime.now(timezone.utc) + timedelta(days=7)
        db_session.commit()

        cancel_token = _cancel_token(test_user)
        with patch("src.routers.auth.enqueue", new=AsyncMock()) as mock_enqueue:
            response = anon_client.post("/auth/cancel-delete/", json={"cancel_token": cancel_token})
        assert response.status_code == 200
        mock_enqueue.assert_called_once_with(
            "send_delete_account_cancelled_email_job", to=test_user.email, name=test_user.display_name
        )

    def test_wrong_purpose_token_rejected(self, anon_client, test_user):
        bad_token = _cancel_token(test_user, purpose="something_else")
        response = anon_client.post("/auth/cancel-delete/", json={"cancel_token": bad_token})
        assert response.status_code == 400
