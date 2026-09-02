import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

from src.auth.security import SecurityUtils


class TestFrontendUrlFallback:
    """FRONTEND_URL missing in production must not silently produce a
    localhost link in verification/deletion emails — it previously did
    because three call sites hardcoded their own `http://localhost:5173`
    fallback instead of sharing one production-safe default.
    """

    def test_helper_falls_back_to_production_domain(self, monkeypatch):
        from src.routers.auth import _get_frontend_url
        monkeypatch.delenv("FRONTEND_URL", raising=False)
        assert _get_frontend_url() == "https://cancer-bot.com"

    def test_helper_respects_explicit_env_var(self, monkeypatch):
        from src.routers.auth import _get_frontend_url
        monkeypatch.setenv("FRONTEND_URL", "https://staging.cancer-bot.com")
        assert _get_frontend_url() == "https://staging.cancer-bot.com"

    def test_register_verification_email_uses_production_link_when_unset(self, anon_client, monkeypatch):
        monkeypatch.delenv("FRONTEND_URL", raising=False)
        captured = {}

        async def fake_enqueue(job_name, **kwargs):
            captured["job_name"] = job_name
            captured["frontend_url"] = kwargs.get("frontend_url")

        monkeypatch.setattr("src.routers.auth.enqueue", fake_enqueue)

        anon_client.post(
            "/auth/register/",
            json={
                "first_name": "No", "last_name": "Env",
                "email": "noenv@example.com",
                "password": "SecurePass123!",
            },
        )

        assert captured["job_name"] == "send_verification_email_job"
        assert captured["frontend_url"] == "https://cancer-bot.com"


class TestRegister:
    def test_register_success_returns_201(self, anon_client):
        response = anon_client.post(
            "/auth/register/",
            json={
                "first_name": "New", "last_name": "User",
                "email": "newuser@example.com",
                "password": "SecurePass123!",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"

    def test_register_succeeds_when_the_verification_email_fails(self, anon_client, monkeypatch):
        """A SendGrid outage (or a stale API key returning 401) must not turn a
        successful registration into an unhandled ASGI traceback. The email is a
        BackgroundTask that runs after the 201 is already sent, so a propagating
        exception can't reach the client — it only pollutes the logs.

        TestClient runs background tasks inline, so this exercises the real path.
        """
        import src.utils.email as email_module

        def boom(*args, **kwargs):
            raise RuntimeError("HTTP Error 401: Unauthorized")

        monkeypatch.setattr(email_module, "_send_sendgrid", boom)

        response = anon_client.post(
            "/auth/register/",
            json={
                "first_name": "Mail", "last_name": "Down",
                "email": "maildown@example.com",
                "password": "SecurePass123!",
            },
        )

        assert response.status_code == 201
        assert response.json()["email"] == "maildown@example.com"

    def test_register_persists_first_and_last_name(self, anon_client, db_session):
        anon_client.post(
            "/auth/register/",
            json={
                "first_name": "Ada", "last_name": "Lovelace",
                "email": "ada@example.com",
                "password": "SecurePass123!",
            },
        )
        from src.db.repositories.users import get_user_by_email
        user = get_user_by_email(db_session, "ada@example.com")
        assert user.first_name == "Ada"
        assert user.last_name == "Lovelace"
        assert user.display_name == "Ada Lovelace"

    def test_register_missing_last_name_returns_422(self, anon_client):
        response = anon_client.post(
            "/auth/register/",
            json={"first_name": "Solo", "email": "solo@example.com", "password": "SecurePass123!"},
        )
        assert response.status_code == 422

    def test_register_duplicate_email_returns_400(self, anon_client, test_user):
        response = anon_client.post(
            "/auth/register/",
            json={
                "first_name": "Another", "last_name": "User",
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
                "first_name": "Reg", "last_name": "User",
                "email": "user@example.com",
                "password": "short",
            },
        )
        assert response.status_code == 400


class TestRegistrationCap:
    """MAX_USERS gates new registrations for a slow-growth rollout. Blank/unset
    must behave exactly like today (no cap) — every other registration test in
    this file relies on that default."""

    def test_registration_open_when_max_users_unset(self, anon_client, monkeypatch):
        monkeypatch.delenv("MAX_USERS", raising=False)
        response = anon_client.get("/auth/registration_status/")
        assert response.status_code == 200
        assert response.json() == {"open": True}

    def test_registration_open_below_cap(self, anon_client, monkeypatch, test_user):
        monkeypatch.setenv("MAX_USERS", "100")
        response = anon_client.get("/auth/registration_status/")
        assert response.json() == {"open": True}

    def test_registration_closed_at_cap(self, anon_client, monkeypatch, test_user):
        monkeypatch.setenv("MAX_USERS", "1")
        response = anon_client.get("/auth/registration_status/")
        assert response.json() == {"open": False}

    def test_registration_status_does_not_disclose_count(self, anon_client, monkeypatch, test_user):
        monkeypatch.setenv("MAX_USERS", "1")
        response = anon_client.get("/auth/registration_status/")
        assert set(response.json().keys()) == {"open"}

    def test_register_rejected_when_at_cap(self, anon_client, monkeypatch, test_user):
        monkeypatch.setenv("MAX_USERS", "1")
        response = anon_client.post(
            "/auth/register/",
            json={
                "first_name": "Late", "last_name": "Comer",
                "email": "latecomer@example.com",
                "password": "SecurePass123!",
            },
        )
        assert response.status_code == 403

    def test_register_succeeds_below_cap(self, anon_client, monkeypatch, test_user):
        monkeypatch.setenv("MAX_USERS", "5")
        response = anon_client.post(
            "/auth/register/",
            json={
                "first_name": "Room", "last_name": "Enough",
                "email": "roomenough@example.com",
                "password": "SecurePass123!",
            },
        )
        assert response.status_code == 201

    def test_register_not_blocked_by_blank_max_users(self, anon_client, monkeypatch):
        monkeypatch.setenv("MAX_USERS", "")
        response = anon_client.post(
            "/auth/register/",
            json={
                "first_name": "No", "last_name": "Cap",
                "email": "nocap@example.com",
                "password": "SecurePass123!",
            },
        )
        assert response.status_code == 201


class TestWaitlist:
    def test_join_waitlist_returns_201(self, anon_client):
        response = anon_client.post("/auth/waitlist/", json={"email": "waitlisted@example.com"})
        assert response.status_code == 201

    def test_join_waitlist_enqueues_confirmation_email(self, anon_client, monkeypatch):
        captured = {}

        async def fake_enqueue(job_name, **kwargs):
            captured["job_name"] = job_name
            captured["to"] = kwargs.get("to")

        monkeypatch.setattr("src.routers.auth.enqueue", fake_enqueue)

        anon_client.post("/auth/waitlist/", json={"email": "notify-me@example.com"})

        assert captured["job_name"] == "send_waitlist_joined_email_job"
        assert captured["to"] == "notify-me@example.com"

    def test_join_waitlist_persists_email(self, anon_client, db_session):
        anon_client.post("/auth/waitlist/", json={"email": "persisted@example.com"})
        from src.db.models import WaitlistEntry
        entry = db_session.query(WaitlistEntry).filter(WaitlistEntry.email == "persisted@example.com").first()
        assert entry is not None

    def test_join_waitlist_twice_does_not_duplicate(self, anon_client, db_session):
        anon_client.post("/auth/waitlist/", json={"email": "dupe@example.com"})
        anon_client.post("/auth/waitlist/", json={"email": "dupe@example.com"})
        from src.db.models import WaitlistEntry
        count = db_session.query(WaitlistEntry).filter(WaitlistEntry.email == "dupe@example.com").count()
        assert count == 1

    def test_join_waitlist_invalid_email_returns_422(self, anon_client):
        response = anon_client.post("/auth/waitlist/", json={"email": "not-an-email"})
        assert response.status_code == 422

    def test_join_waitlist_blocked_after_limit(self, anon_client):
        from src.db.repositories.rate_limit import MAX_WAITLIST_ATTEMPTS
        for i in range(MAX_WAITLIST_ATTEMPTS):
            anon_client.post("/auth/waitlist/", json={"email": f"limit{i}@example.com"})
        response = anon_client.post("/auth/waitlist/", json={"email": "onemore@example.com"})
        assert response.status_code == 429


class TestResendVerification:
    """/resend-verification/ was the only token-issuing endpoint with no non-prod
    escape hatch: only the token's SHA-256 hash is stored, so a token that isn't
    returned here cannot be recovered afterwards."""

    def _unverified(self, db_session):
        from src.db.repositories.users import create_user
        user = create_user(
            db_session,
            first_name="Un", last_name="Verified",
            email="unverified@example.com",
            password_hash=SecurityUtils.hash_password("TestPass123!"),
        )
        user.email_verified = False
        db_session.commit()
        return user

    def test_returns_token_in_non_prod(self, anon_client, db_session):
        self._unverified(db_session)

        response = anon_client.post(
            "/auth/resend-verification/", json={"email": "unverified@example.com"}
        )

        assert response.status_code == 200
        assert response.json()["verification_token"]

    def test_never_returns_token_in_prod(self, anon_client, db_session, monkeypatch):
        self._unverified(db_session)
        monkeypatch.setattr("src.routers.auth.is_prod", lambda: True)

        response = anon_client.post(
            "/auth/resend-verification/", json={"email": "unverified@example.com"}
        )

        assert response.status_code == 200
        assert "verification_token" not in response.json()

    def test_response_does_not_reveal_whether_the_email_exists(self, anon_client, test_user):
        """An unknown address and an already-verified one must look identical."""
        unknown = anon_client.post(
            "/auth/resend-verification/", json={"email": "nobody@example.com"}
        )
        verified = anon_client.post(
            "/auth/resend-verification/", json={"email": test_user.email}
        )

        assert unknown.status_code == verified.status_code == 200
        assert unknown.json() == verified.json() == {"ok": True}


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

    def test_login_wrong_password_reports_remaining_attempts(self, anon_client, test_user):
        response = anon_client.post(
            "/auth/login/",
            json={"email": test_user.email, "password": "WrongPassword", "rememberMe": False},
        )
        assert response.status_code == 401
        assert "4 attempt(s) remaining" in response.json()["detail"]

    def test_login_locks_account_after_max_failed_attempts(self, anon_client, test_user):
        for _ in range(4):
            anon_client.post(
                "/auth/login/",
                json={"email": test_user.email, "password": "WrongPassword", "rememberMe": False},
            )
        response = anon_client.post(
            "/auth/login/",
            json={"email": test_user.email, "password": "WrongPassword", "rememberMe": False},
        )
        assert response.status_code == 429
        assert "locked" in response.json()["detail"].lower()

        # Even the correct password is now rejected until the lockout expires
        response = anon_client.post(
            "/auth/login/",
            json={"email": test_user.email, "password": "TestPass123!", "rememberMe": False},
        )
        assert response.status_code == 429

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
        with patch("src.routers.auth.enqueue", new=AsyncMock()) as mock_enqueue:
            response = anon_client.post("/auth/forgot-password/", json={"email": test_user.email})
            assert response.status_code == 200
            mock_enqueue.assert_called_once()
            job_name, call_kwargs = mock_enqueue.call_args[0][0], mock_enqueue.call_args[1]
            assert job_name == "send_password_reset_email_job"
            assert call_kwargs["to"] == test_user.email
            assert "token=" in call_kwargs["link"]
            # Emails greet with the user's full name (display_name), not just first
            assert call_kwargs["name"] == test_user.display_name == "Test User"

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
        assert "first_name" in data
        assert "last_name" in data

    def test_check_auth_unauthenticated_returns_401(self, anon_client):
        response = anon_client.get("/auth/check")
        assert response.status_code == 401


class TestRateLimiting:
    def test_register_blocked_after_limit(self, anon_client):
        from src.db.repositories.rate_limit import MAX_REGISTER_ATTEMPTS
        payload = {"first_name": "Reg", "last_name": "User", "email": "x@example.com", "password": "SecurePass123!"}
        for _ in range(MAX_REGISTER_ATTEMPTS):
            anon_client.post("/auth/register/", json=payload)
        response = anon_client.post("/auth/register/", json=payload)
        assert response.status_code == 429

    def test_register_not_blocked_before_limit(self, anon_client):
        from src.db.repositories.rate_limit import MAX_REGISTER_ATTEMPTS
        for i in range(MAX_REGISTER_ATTEMPTS - 1):
            anon_client.post("/auth/register/", json={"first_name": "U", "last_name": "U", "email": f"u{i}@x.com", "password": "SecurePass123!"})
        response = anon_client.post("/auth/register/", json={"first_name": "U", "last_name": "U", "email": "last@x.com", "password": "SecurePass123!"})
        assert response.status_code != 429

    def test_forgot_password_blocked_after_limit(self, anon_client, test_user):
        from src.db.repositories.rate_limit import MAX_FORGOT_PASSWORD_ATTEMPTS
        for _ in range(MAX_FORGOT_PASSWORD_ATTEMPTS):
            anon_client.post("/auth/forgot-password/", json={"email": test_user.email})
        response = anon_client.post("/auth/forgot-password/", json={"email": test_user.email})
        assert response.status_code == 429

    def test_forgot_password_not_blocked_before_limit(self, anon_client, test_user):
        from src.db.repositories.rate_limit import MAX_FORGOT_PASSWORD_ATTEMPTS
        for _ in range(MAX_FORGOT_PASSWORD_ATTEMPTS - 1):
            anon_client.post("/auth/forgot-password/", json={"email": test_user.email})
        response = anon_client.post("/auth/forgot-password/", json={"email": test_user.email})
        assert response.status_code == 200

    def test_forgot_password_limit_is_per_email(self, anon_client, test_user):
        from src.db.repositories.rate_limit import MAX_FORGOT_PASSWORD_ATTEMPTS
        for _ in range(MAX_FORGOT_PASSWORD_ATTEMPTS):
            anon_client.post("/auth/forgot-password/", json={"email": test_user.email})
        # Different email is unaffected
        response = anon_client.post("/auth/forgot-password/", json={"email": "other@example.com"})
        assert response.status_code == 200


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
