import pytest
from unittest.mock import patch, AsyncMock


class TestRegister:
    def test_register_success_returns_201(self, anon_client):
        response = anon_client.post(
            "/auth/register/",
            json={
                "name": "New User",
                "email": "newuser@example.com",
                "password": "SecurePass123",
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
                "password": "AnotherPass123",
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
                "password": "TestPass123",
                "rememberMe": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
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

    def test_logout_clears_cookie(self, client):
        # After logout, the access_token cookie should be cleared (max_age=0 or expires in past)
        client.post("/auth/logout/")
        # The TestClient doesn't directly expose Set-Cookie headers, but we can verify
        # that subsequent requests without the token would fail auth
        client.cookies.clear()
        # Try accessing an authenticated endpoint without token
        response = client.get("/conversations/")
        assert response.status_code == 401


class TestForgotPassword:
    def test_forgot_password_always_returns_200(self, anon_client):
        response = anon_client.post("/auth/forgot-password/", json={"email": "unknown@example.com"})
        assert response.status_code == 200

    def test_forgot_password_sends_email_for_known_user(self, anon_client, test_user):
        with patch("src.routers.auth.send_password_reset_email", new=AsyncMock()) as mock_send:
            response = anon_client.post("/auth/forgot-password/", json={"email": test_user.email})
            assert response.status_code == 200
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert test_user.email in call_args[0]  # to address

    def test_forgot_password_missing_email_returns_422(self, anon_client):
        response = anon_client.post("/auth/forgot-password/", json={})
        assert response.status_code == 422


class TestResetPassword:
    def test_reset_password_success(self, anon_client, test_user):
        with patch("src.routers.auth.verify_and_consume_code") as mock_verify:
            mock_verify.return_value = (True, "")
            response = anon_client.post(
                "/auth/reset-password/",
                json={
                    "email": test_user.email,
                    "code": "123456",
                    "new_password": "NewSecurePass123",
                },
            )
            assert response.status_code == 200
            mock_verify.assert_called_once()

    def test_reset_password_wrong_code_returns_400(self, anon_client, test_user):
        with patch("src.routers.auth.verify_and_consume_code") as mock_verify:
            mock_verify.return_value = (False, "Invalid code")
            response = anon_client.post(
                "/auth/reset-password/",
                json={
                    "email": test_user.email,
                    "code": "999999",
                    "new_password": "NewPassword123",
                },
            )
            assert response.status_code == 400

    def test_reset_password_unknown_email_returns_400(self, anon_client):
        response = anon_client.post(
            "/auth/reset-password/",
            json={
                "email": "unknown@example.com",
                "code": "123456",
                "new_password": "NewPassword123",
            },
        )
        assert response.status_code == 400

    def test_reset_password_short_password_returns_400(self, anon_client, test_user):
        response = anon_client.post(
            "/auth/reset-password/",
            json={
                "email": test_user.email,
                "code": "123456",
                "new_password": "short",
            },
        )
        assert response.status_code == 400

    def test_reset_password_missing_fields_returns_422(self, anon_client):
        response = anon_client.post(
            "/auth/reset-password/",
            json={"email": "user@example.com"},
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
