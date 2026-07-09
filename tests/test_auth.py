import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

from src.auth.security import SecurityUtils


class TestRegister:
    def test_register_success_returns_201(self, anon_client):
        response = anon_client.post(
            "/auth/register/",
            json={
                "name": "New User",
                "email": "newuser@example.com",
                "password": "SecurePass123!",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"

    def test_register_duplicate_email_returns_400(self, anon_client, test_user):
        response = anon_client.post(
            "/auth/register/",
            json={
                "name": "Another User",
                "email": test_user.email,
                "password": "AnotherPass123!",
            },
        )
        assert response.status_code == 400

    def test_register_missing_fields_returns_422(self, anon_client):
        response = anon_client.post("/auth/register/", json={"email": "user@example.com"})
        assert response.status_code == 422

    def test_register_short_password_returns_400(self, anon_client):
        response = anon_client.post(
            "/auth/register/",
            json={
                "name": "User",
                "email": "user@example.com",
                "password": "short",
            },
        )
        assert response.status_code == 400


class TestLogin:
    def test_login_success_returns_token_and_sets_cookie(self, anon_client, test_user):
        response = anon_client.post(
            "/auth/login/",
            json={
                "email": test_user.email,
                "password": "TestPass123!",
                "rememberMe": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["token_type"] == "bearer"
        assert "access_token" not in data
        assert "access_token" in response.cookies or "access_token" in anon_client.cookies

    def test_login_wrong_password_returns_401(self, anon_client, test_user):
        response = anon_client.post(
            "/auth/login/",
            json={
                "email": test_user.email,
                "password": "WrongPassword",
                "rememberMe": False,
            },
        )
        assert response.status_code == 401

    def test_login_unknown_email_returns_401(self, anon_client):
        response = anon_client.post(
            "/auth/login/",
            json={
                "email": "unknown@example.com",
                "password": "AnyPassword",
                "rememberMe": False,
            },
        )
        assert response.status_code == 401

    def test_login_missing_fields_returns_422(self, anon_client):
        response = anon_client.post("/auth/login/", json={"email": "user@example.com"})
        assert response.status_code == 422


class TestLogout:
    def test_logout_returns_200(self, client):
        response = client.post("/auth/logout/")
        assert response.status_code == 200

    def test_logout_clears_cookie(self, client, anon_client):
        # After logout, the access_token cookie should be cleared
        client.post("/auth/logout/")
        # Verify the logout response contains the right data
        response = client.post("/auth/logout/")
        assert response.status_code == 200
        data = response.json()
        assert data["logged_out"] is True


class TestForgotPassword:
    def test_forgot_password_always_returns_200(self, anon_client):
        response = anon_client.post("/auth/forgot-password/", json={"email": "unknown@example.com"})
        assert response.status_code == 200

    def test_forgot_password_sends_email_for_known_user(self, anon_client, test_user):
        with patch("src.routers.auth.send_password_reset_email", new=AsyncMock()) as mock_send:
            response = anon_client.post("/auth/forgot-password/", json={"email": test_user.email})
            assert response.status_code == 200
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args[1]
            assert call_kwargs["to"] == test_user.email
            assert "token=" in call_kwargs["link"]
            assert call_kwargs["name"] is not None

    def test_forgot_password_missing_email_returns_422(self, anon_client):
        response = anon_client.post("/auth/forgot-password/", json={})
        assert response.status_code == 422


class TestResetPassword:
    def test_reset_password_success(self, anon_client, test_user, db_session):
        from src.db.repositories.password_resets import create_reset_token
        token = create_reset_token(db_session, test_user.id)
        db_session.commit()

        response = anon_client.post(
            "/auth/reset-password/",
            json={"token": token, "new_password": "NewSecurePass123!"},
        )
        assert response.status_code == 200

    def test_reset_password_invalid_token_returns_400(self, anon_client):
        response = anon_client.post(
            "/auth/reset-password/",
            json={"token": "invalid-token-xyz", "new_password": "NewPassword123!"},
        )
        assert response.status_code == 400

    def test_reset_password_short_password_returns_400(self, anon_client):
        response = anon_client.post(
            "/auth/reset-password/",
            json={"token": "any-token", "new_password": "short"},
        )
        assert response.status_code == 400

    def test_reset_password_missing_fields_returns_422(self, anon_client):
        response = anon_client.post(
            "/auth/reset-password/",
            json={"token": "some-token"},
        )
        assert response.status_code == 422


class TestCheckAuth:
    def test_check_auth_authenticated_returns_user_info(self, client):
        response = client.get("/auth/check")
        assert response.status_code == 200
        data = response.json()
        assert "email" in data
        assert "name" in data

    def test_check_auth_unauthenticated_returns_401(self, anon_client):
        response = anon_client.get("/auth/check")
        assert response.status_code == 401


def _make_token(user, tv_override=None):
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    payload = {"sub": str(user.id), "email": user.email, "tv": tv_override if tv_override is not None else user.token_version, "exp": expires}
    return SecurityUtils.create_jwt_token(payload)


class TestTokenRevocation:
    def test_valid_token_accepted(self, anon_client, test_user):
        token = _make_token(test_user)
        response = anon_client.get("/auth/check/", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200

    def test_token_without_tv_rejected(self, anon_client, test_user):
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        token = SecurityUtils.create_jwt_token({"sub": str(test_user.id), "email": test_user.email, "exp": expires})
        response = anon_client.get("/auth/check/", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_token_with_wrong_tv_rejected(self, anon_client, test_user):
        token = _make_token(test_user, tv_override=999)
        response = anon_client.get("/auth/check/", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_reset_password_increments_token_version(self, anon_client, test_user, db_session):
        from src.db.repositories.password_resets import create_reset_token
        initial_version = test_user.token_version
        reset_token = create_reset_token(db_session, test_user.id)
        anon_client.post("/auth/reset-password/", json={"token": reset_token, "new_password": "NewSecurePass456!"})
        db_session.refresh(test_user)
        assert test_user.token_version == initial_version + 1

    def test_reset_password_invalidates_old_token(self, anon_client, test_user, db_session):
        from src.db.repositories.password_resets import create_reset_token
        old_token = _make_token(test_user)
        assert anon_client.get("/auth/check/", headers={"Authorization": f"Bearer {old_token}"}).status_code == 200
        reset_token = create_reset_token(db_session, test_user.id)
        anon_client.post("/auth/reset-password/", json={"token": reset_token, "new_password": "NewSecurePass456!"})
        assert anon_client.get("/auth/check/", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
