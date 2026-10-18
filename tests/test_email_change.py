from unittest.mock import patch, AsyncMock

from src.db import models
from src.db.repositories.tokens import (
    create_email_change_request_token,
    create_email_change_token,
    create_email_revert_token,
)


def _request_email_change(client):
    return client.post("/auth/request-email-change/")


def _submit_new_email(client, token: str, new_email: str):
    return client.post("/auth/change-email/", json={"token": token, "new_email": new_email})


def _confirm_email_change(client, token: str):
    return client.get(f"/auth/confirm-email-change/?token={token}")


def _revert_email(client, token: str):
    return client.get(f"/auth/revert-email/?token={token}")


class TestRequestEmailChange:
    def test_success_sends_email_and_creates_token(self, client, test_user, db_session):
        with patch("src.routers.auth.enqueue", new=AsyncMock()) as mock_send:
            response = _request_email_change(client)
        assert response.status_code == 200
        assert response.json()["ok"] is True
        mock_send.assert_called_once()

        db_session.expire_all()
        tokens = db_session.query(models.Token).filter(
            models.Token.user_id == test_user.id,
            models.Token.token_type == "email_change_request",
        ).all()
        assert len(tokens) == 1

    def test_non_prod_response_includes_token_for_automation(self, client):
        with patch("src.routers.auth.enqueue", new=AsyncMock()):
            response = _request_email_change(client)
        assert response.json()["email_change_request_token"]

    def test_unauthenticated_returns_401(self, anon_client):
        assert anon_client.post("/auth/request-email-change/").status_code == 401

    def test_rate_limited_after_max_attempts(self, client):
        from src.db.repositories.rate_limit import MAX_EMAIL_CHANGE_ATTEMPTS
        with patch("src.routers.auth.enqueue", new=AsyncMock()):
            for _ in range(MAX_EMAIL_CHANGE_ATTEMPTS):
                assert _request_email_change(client).status_code == 200
            blocked = _request_email_change(client)
        assert blocked.status_code == 429


class TestSubmitNewEmail:
    def test_success_creates_change_token_and_sends_verification(self, client, test_user, db_session):
        token = create_email_change_request_token(db_session, test_user.id)
        with patch("src.routers.auth.enqueue", new=AsyncMock()) as mock_send:
            response = _submit_new_email(client, token, "new@example.com")
        assert response.status_code == 200
        assert response.json()["ok"] is True
        mock_send.assert_called_once()
        assert mock_send.call_args.args[0] == "send_email_change_verification_email_job"
        assert mock_send.call_args.kwargs["to"] == "new@example.com"

        db_session.expire_all()
        change_tokens = db_session.query(models.Token).filter(
            models.Token.user_id == test_user.id,
            models.Token.token_type == "email_change",
        ).all()
        assert len(change_tokens) == 1
        assert change_tokens[0].target_email == "new@example.com"

        # The step-1 token must be consumed so the link can't be reused.
        request_token = db_session.query(models.Token).filter(
            models.Token.user_id == test_user.id,
            models.Token.token_type == "email_change_request",
        ).first()
        assert request_token.used_at is not None

    def test_non_prod_response_includes_token_for_automation(self, client, test_user, db_session):
        token = create_email_change_request_token(db_session, test_user.id)
        with patch("src.routers.auth.enqueue", new=AsyncMock()):
            response = _submit_new_email(client, token, "new@example.com")
        assert response.json()["email_change_token"]

    def test_ninja_email_is_rejected(self, client, test_user, db_session, monkeypatch):
        monkeypatch.setenv("NINJA_EMAIL", "ninja-test@example.com")
        token = create_email_change_request_token(db_session, test_user.id)
        response = _submit_new_email(client, token, "ninja-test@example.com")
        assert response.status_code == 400

    def test_same_email_returns_400(self, client, test_user, db_session):
        token = create_email_change_request_token(db_session, test_user.id)
        response = _submit_new_email(client, token, test_user.email)
        assert response.status_code == 400

    def test_already_registered_email_returns_400(self, client, test_user, db_session):
        from src.db.repositories.users import create_user
        create_user(
            db_session, first_name="Other", last_name="User",
            email="taken@example.com",
        )
        token = create_email_change_request_token(db_session, test_user.id)
        response = _submit_new_email(client, token, "taken@example.com")
        assert response.status_code == 400

    def test_invalid_token_returns_400(self, client):
        response = _submit_new_email(client, "not-a-real-token", "new@example.com")
        assert response.status_code == 400

    def test_reused_token_returns_400(self, client, test_user, db_session):
        token = create_email_change_request_token(db_session, test_user.id)
        with patch("src.routers.auth.enqueue", new=AsyncMock()):
            first = _submit_new_email(client, token, "new@example.com")
        assert first.status_code == 200
        second = _submit_new_email(client, token, "another@example.com")
        assert second.status_code == 400


class TestConfirmEmailChange:
    def test_success_swaps_email_and_sends_revert_notice(self, client, test_user, db_session):
        token = create_email_change_token(db_session, test_user.id, "new@example.com")
        with patch("src.routers.auth.enqueue", new=AsyncMock()) as mock_send:
            response = _confirm_email_change(client, token)
        assert response.status_code == 200
        assert response.json()["ok"] is True
        mock_send.assert_called_once()
        assert mock_send.call_args.args[0] == "send_email_changed_notice_email_job"
        assert mock_send.call_args.kwargs["to"] == "testuser@example.com"

        db_session.expire_all()
        user = db_session.query(models.User).filter(models.User.id == test_user.id).first()
        assert user.email == "new@example.com"
        assert user.email_verified is True
        assert user.token_version == 2

        revert_tokens = db_session.query(models.Token).filter(
            models.Token.user_id == test_user.id,
            models.Token.token_type == "email_revert",
        ).all()
        assert len(revert_tokens) == 1
        assert revert_tokens[0].target_email == "testuser@example.com"

    def test_non_prod_response_includes_revert_token_for_automation(self, client, test_user, db_session):
        token = create_email_change_token(db_session, test_user.id, "new@example.com")
        with patch("src.routers.auth.enqueue", new=AsyncMock()):
            response = _confirm_email_change(client, token)
        assert response.json()["email_revert_token"]

    def test_invalid_token_returns_400(self, client):
        assert _confirm_email_change(client, "not-a-real-token").status_code == 400

    def test_email_taken_in_the_meantime_returns_400(self, client, test_user, db_session):
        from src.db.repositories.users import create_user
        token = create_email_change_token(db_session, test_user.id, "new@example.com")
        create_user(
            db_session, first_name="Other", last_name="User",
            email="new@example.com",
        )
        response = _confirm_email_change(client, token)
        assert response.status_code == 400

    def test_reused_token_is_idempotent_when_email_still_matches(self, client, test_user, db_session):
        """Same StrictMode double-fetch hazard as revert-email's equivalent
        test above — the losing duplicate request must see success too."""
        token = create_email_change_token(db_session, test_user.id, "new@example.com")
        with patch("src.routers.auth.enqueue", new=AsyncMock()):
            first = _confirm_email_change(client, token)
        assert first.status_code == 200
        second = _confirm_email_change(client, token)
        assert second.status_code == 200
        assert second.json()["ok"] is True

    def test_reused_token_after_email_changed_again_returns_400(self, client, test_user, db_session):
        token = create_email_change_token(db_session, test_user.id, "new@example.com")
        with patch("src.routers.auth.enqueue", new=AsyncMock()):
            first = _confirm_email_change(client, token)
        assert first.status_code == 200

        user = db_session.query(models.User).filter(models.User.id == test_user.id).first()
        user.email = "moved-on@example.com"
        db_session.commit()

        second = _confirm_email_change(client, token)
        assert second.status_code == 400


class TestRevertEmail:
    def test_success_restores_old_email(self, client, test_user, db_session):
        test_user_email = test_user.email
        user = db_session.query(models.User).filter(models.User.id == test_user.id).first()
        user.email = "new@example.com"
        db_session.commit()

        token = create_email_revert_token(db_session, test_user.id, test_user_email)
        response = _revert_email(client, token)
        assert response.status_code == 200

        db_session.expire_all()
        reverted = db_session.query(models.User).filter(models.User.id == test_user.id).first()
        assert reverted.email == test_user_email
        assert reverted.email_verified is True
        assert reverted.token_version == 2

    def test_invalid_token_returns_400(self, client):
        assert _revert_email(client, "not-a-real-token").status_code == 400

    def test_reused_token_after_email_changed_again_returns_400(self, client, test_user, db_session):
        """A stale reused token is only idempotent-safe while the account's
        email still matches what it set — if it's since moved on again,
        replaying the old token must fail rather than silently reverting."""
        token = create_email_revert_token(db_session, test_user.id, "old@example.com")
        first = _revert_email(client, token)
        assert first.status_code == 200

        user = db_session.query(models.User).filter(models.User.id == test_user.id).first()
        user.email = "moved-on@example.com"
        db_session.commit()

        second = _revert_email(client, token)
        assert second.status_code == 400

    def test_reused_token_is_idempotent_when_email_still_matches(self, client, test_user, db_session):
        """Guards against a real bug: ConfirmEmailChange.tsx/RevertEmail.tsx
        fire their GET from a bare useEffect, which React StrictMode
        double-invokes in dev, sending the single-use token twice. The
        losing request must not surface as a failure when the action it
        asked for already happened — same as verify_email's
        already_verified fallback."""
        token = create_email_revert_token(db_session, test_user.id, "old@example.com")
        first = _revert_email(client, token)
        assert first.status_code == 200
        second = _revert_email(client, token)
        assert second.status_code == 200
        assert second.json()["ok"] is True
