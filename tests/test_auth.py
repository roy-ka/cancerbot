import pytest
from datetime import datetime, timedelta, timezone

from src.auth.security import SecurityUtils


@pytest.fixture
def sent_codes(monkeypatch):
    """Capture every login-code email instead of enqueueing it, keyed by
    address — the tests read codes from here, the way a user reads them from
    their inbox."""
    codes: dict[str, str] = {}

    async def fake_enqueue(job_name, **kwargs):
        if job_name == "send_login_code_email_job":
            codes[kwargs["to"]] = kwargs["code"]

    monkeypatch.setattr("src.routers.auth.enqueue", fake_enqueue)
    return codes


def _register(client, email="newuser@example.com", first_name="New", last_name="User"):
    return client.post(
        "/auth/register/",
        json={"first_name": first_name, "last_name": last_name, "email": email},
    )


def _verify(client, email, code, remember_me=False):
    return client.post(
        "/auth/verify-code/",
        json={"email": email, "code": code, "rememberMe": remember_me},
    )


def _wrong(code: str) -> str:
    return "000000" if code != "000000" else "111111"


class TestFrontendUrlFallback:
    """Every emailed link goes through one helper. Outside production it
    falls back to the local dev frontend; production can't reach the
    fallback because src/main.py refuses to start without FRONTEND_URL
    (see TestMissingFrontendUrlGuard in test_low_severity_hardening.py).
    """

    def test_helper_falls_back_to_local_dev_frontend(self, monkeypatch):
        from src.routers.auth import _get_frontend_url
        monkeypatch.delenv("FRONTEND_URL", raising=False)
        assert _get_frontend_url() == "http://localhost:5173"

    def test_blank_value_is_treated_as_unset(self, monkeypatch):
        from src.routers.auth import _get_frontend_url
        monkeypatch.setenv("FRONTEND_URL", "  ")
        assert _get_frontend_url() == "http://localhost:5173"

    def test_helper_respects_explicit_env_var(self, monkeypatch):
        from src.routers.auth import _get_frontend_url
        monkeypatch.setenv("FRONTEND_URL", "https://staging.cancer-bot.com")
        assert _get_frontend_url() == "https://staging.cancer-bot.com"


class TestRegister:
    def test_registration_is_never_capped(self, anon_client, test_user, monkeypatch):
        """The MAX_USERS cap and waitlist were removed; a value left over in
        an old .env must not bring the cap back."""
        monkeypatch.setenv("MAX_USERS", "1")
        response = _register(anon_client, email="overcap@example.com")
        assert response.status_code == 201
        assert anon_client.get("/auth/registration_status/").status_code == 404

    def test_register_emails_a_code_and_returns_201(self, anon_client, sent_codes):
        response = _register(anon_client)
        assert response.status_code == 201
        assert response.json()["email"] == "newuser@example.com"
        assert len(sent_codes["newuser@example.com"]) == 6
        # The code goes to the inbox only — never into a response here.
        assert "dev_code" not in response.json()

    def test_account_is_unverified_until_the_code_is_entered(self, anon_client, db_session, sent_codes):
        from src.db.repositories.users import get_user_by_email
        _register(anon_client)
        user = get_user_by_email(db_session, "newuser@example.com")
        assert user.email_verified is False
        assert user.password_hash is None

        response = _verify(anon_client, "newuser@example.com", sent_codes["newuser@example.com"])
        assert response.status_code == 200
        db_session.refresh(user)
        assert user.email_verified is True
        assert "access_token" in anon_client.cookies

    def test_register_succeeds_when_the_email_fails(self, anon_client, monkeypatch):
        """A Brevo outage must not turn a successful registration into a 500
        — the send runs as a separate worker job."""
        import src.utils.email as email_module

        def boom(*args, **kwargs):
            raise RuntimeError("HTTP Error 401: Unauthorized")

        monkeypatch.setattr(email_module, "_send_brevo", boom)
        response = _register(anon_client, email="maildown@example.com")
        assert response.status_code == 201

    def test_register_persists_first_and_last_name(self, anon_client, db_session):
        _register(anon_client, email="ada@example.com", first_name="Ada", last_name="Lovelace")
        from src.db.repositories.users import get_user_by_email
        user = get_user_by_email(db_session, "ada@example.com")
        assert user.first_name == "Ada"
        assert user.last_name == "Lovelace"
        assert user.display_name == "Ada Lovelace"

    def test_reregistering_an_unverified_address_sends_a_new_code(self, anon_client, db_session, sent_codes):
        """An abandoned sign-up must not lock the address out."""
        from src.db.repositories.users import get_user_by_email
        _register(anon_client, email="again@example.com", first_name="First")
        response = _register(anon_client, email="again@example.com", first_name="Second")
        assert response.status_code == 201
        assert get_user_by_email(db_session, "again@example.com").first_name == "Second"
        assert _verify(anon_client, "again@example.com", sent_codes["again@example.com"]).status_code == 200

    def test_register_missing_last_name_returns_422(self, anon_client):
        response = anon_client.post(
            "/auth/register/", json={"first_name": "Solo", "email": "solo@example.com"},
        )
        assert response.status_code == 422

    def test_register_duplicate_email_returns_400(self, anon_client, test_user):
        response = _register(anon_client, email=test_user.email)
        assert response.status_code == 400

    def test_register_ninja_email_returns_400(self, anon_client, monkeypatch):
        monkeypatch.setenv("NINJA_EMAIL", "ninja-test@example.com")
        response = _register(anon_client, email="ninja-test@example.com")
        assert response.status_code == 400

    def test_register_missing_fields_returns_422(self, anon_client):
        response = anon_client.post("/auth/register/", json={"email": "user@example.com"})
        assert response.status_code == 422

    def test_a_password_field_is_ignored(self, anon_client, db_session):
        """Old clients may still send one; it's dropped, never stored."""
        from src.db.repositories.users import get_user_by_email
        response = anon_client.post(
            "/auth/register/",
            json={"first_name": "Old", "last_name": "Client",
                  "email": "oldclient@example.com", "password": "SecurePass123!"},
        )
        assert response.status_code == 201
        assert get_user_by_email(db_session, "oldclient@example.com").password_hash is None


class TestRequestCode:
    def test_known_user_gets_a_code(self, anon_client, test_user, sent_codes):
        response = anon_client.post("/auth/request-code/", json={"email": test_user.email})
        assert response.status_code == 200
        assert response.json() == {"ok": True, "email": test_user.email}
        assert len(sent_codes[test_user.email]) == 6

    def test_unknown_email_gets_the_same_response_and_no_email(self, anon_client, sent_codes):
        response = anon_client.post("/auth/request-code/", json={"email": "nobody@example.com"})
        assert response.status_code == 200
        assert response.json() == {"ok": True, "email": "nobody@example.com"}
        assert sent_codes == {}

    def test_never_returns_the_code_without_dev_shortcuts(self, anon_client, test_user, monkeypatch):
        """Non-production alone is not enough: a code in the response is a
        login, so staging must not hand it out."""
        monkeypatch.setattr("src.routers.auth.is_prod", lambda: False)
        response = anon_client.post("/auth/request-code/", json={"email": test_user.email})
        assert "dev_code" not in response.json()

    def test_invalid_email_returns_422(self, anon_client):
        response = anon_client.post("/auth/request-code/", json={"email": "not-an-email"})
        assert response.status_code == 422


class TestVerifyCode:
    def test_correct_code_sets_cookie(self, anon_client, test_user, sent_codes):
        anon_client.post("/auth/request-code/", json={"email": test_user.email})
        response = _verify(anon_client, test_user.email, sent_codes[test_user.email])
        assert response.status_code == 200
        data = response.json()
        assert data == {"token_type": "bearer", "is_ninja": False}
        assert "access_token" in anon_client.cookies
        assert anon_client.get("/auth/check/").status_code == 200

    def test_code_works_only_once(self, anon_client, test_user, sent_codes):
        anon_client.post("/auth/request-code/", json={"email": test_user.email})
        code = sent_codes[test_user.email]
        assert _verify(anon_client, test_user.email, code).status_code == 200
        assert _verify(anon_client, test_user.email, code).status_code == 401

    def test_wrong_code_returns_401_with_remaining_attempts(self, anon_client, test_user, sent_codes):
        from src.db.repositories.tokens import LOGIN_CODE_MAX_ATTEMPTS
        anon_client.post("/auth/request-code/", json={"email": test_user.email})
        response = _verify(anon_client, test_user.email, _wrong(sent_codes[test_user.email]))
        assert response.status_code == 401
        assert f"{LOGIN_CODE_MAX_ATTEMPTS - 1} attempt(s) left" in response.json()["detail"]
        assert "access_token" not in anon_client.cookies

    def test_code_dies_after_max_wrong_attempts(self, anon_client, test_user, sent_codes):
        from src.db.repositories.tokens import LOGIN_CODE_MAX_ATTEMPTS
        anon_client.post("/auth/request-code/", json={"email": test_user.email})
        code = sent_codes[test_user.email]
        for _ in range(LOGIN_CODE_MAX_ATTEMPTS):
            _verify(anon_client, test_user.email, _wrong(code))
        response = _verify(anon_client, test_user.email, code)
        assert response.status_code == 401
        assert "too many" in response.json()["detail"].lower()

    def test_a_new_code_works_after_the_old_one_died(self, anon_client, test_user, sent_codes):
        from src.db.repositories.tokens import LOGIN_CODE_MAX_ATTEMPTS
        anon_client.post("/auth/request-code/", json={"email": test_user.email})
        for _ in range(LOGIN_CODE_MAX_ATTEMPTS):
            _verify(anon_client, test_user.email, _wrong(sent_codes[test_user.email]))
        anon_client.post("/auth/request-code/", json={"email": test_user.email})
        assert _verify(anon_client, test_user.email, sent_codes[test_user.email]).status_code == 200

    def test_unknown_email_returns_401(self, anon_client):
        response = _verify(anon_client, "unknown@example.com", "123456")
        assert response.status_code == 401

    def test_code_for_one_address_does_not_work_for_another(self, anon_client, test_user, db_session, sent_codes):
        from src.db.repositories.users import create_user
        other = create_user(db_session, first_name="O", last_name="U", email="other@example.com")
        other.email_verified = True
        db_session.commit()
        anon_client.post("/auth/request-code/", json={"email": test_user.email})
        response = _verify(anon_client, "other@example.com", sent_codes[test_user.email])
        assert response.status_code == 401

    def test_expired_code_returns_401(self, anon_client, test_user, sent_codes):
        from freezegun import freeze_time
        with freeze_time(datetime.now(timezone.utc)):
            anon_client.post("/auth/request-code/", json={"email": test_user.email})
        with freeze_time(datetime.now(timezone.utc) + timedelta(minutes=11)):
            response = _verify(anon_client, test_user.email, sent_codes[test_user.email])
        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()

    @pytest.mark.parametrize("code", ["12345", "1234567", "abcdef", "12 456", ""])
    def test_malformed_code_returns_422(self, anon_client, test_user, code):
        response = _verify(anon_client, test_user.email, code)
        assert response.status_code == 422

    def test_remember_me_sets_a_persistent_cookie_in_production(self, anon_client, test_user, sent_codes, monkeypatch):
        monkeypatch.setattr("src.routers.auth.is_prod", lambda: True)
        anon_client.post("/auth/request-code/", json={"email": test_user.email})
        response = _verify(anon_client, test_user.email, sent_codes[test_user.email], remember_me=True)
        assert "Max-Age=2592000" in response.headers["set-cookie"]

    def test_session_cookie_without_remember_me_in_production(self, anon_client, test_user, sent_codes, monkeypatch):
        monkeypatch.setattr("src.routers.auth.is_prod", lambda: True)
        anon_client.post("/auth/request-code/", json={"email": test_user.email})
        response = _verify(anon_client, test_user.email, sent_codes[test_user.email])
        assert "Max-Age" not in response.headers["set-cookie"]

    def test_code_issued_before_an_email_change_stops_working(self, anon_client, test_user, db_session, sent_codes):
        anon_client.post("/auth/request-code/", json={"email": test_user.email})
        code = sent_codes[test_user.email]
        test_user.email = "moved@example.com"
        db_session.commit()
        assert _verify(anon_client, "testuser@example.com", code).status_code == 401


class TestDevEmailShortcuts:
    """DEV_EMAIL_SHORTCUTS (local dev only): the code is also returned in
    the response so local development and E2E need no inbox."""

    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch):
        monkeypatch.setenv("DEV_EMAIL_SHORTCUTS", "true")

    def test_register_returns_a_working_code(self, anon_client):
        response = _register(anon_client, email="dev@example.com")
        code = response.json()["dev_code"]
        assert _verify(anon_client, "dev@example.com", code).status_code == 200

    def test_request_code_returns_a_working_code(self, anon_client, test_user):
        response = anon_client.post("/auth/request-code/", json={"email": test_user.email})
        code = response.json()["dev_code"]
        assert _verify(anon_client, test_user.email, code).status_code == 200

    def test_unknown_email_still_returns_no_code(self, anon_client):
        response = anon_client.post("/auth/request-code/", json={"email": "nobody@example.com"})
        assert "dev_code" not in response.json()

    def test_ignored_in_production(self, monkeypatch):
        from src.utils.utils import dev_email_shortcuts
        monkeypatch.setattr("src.utils.utils.ENV", "production")
        assert dev_email_shortcuts() is False

    def test_off_by_default(self, anon_client, test_user, monkeypatch):
        monkeypatch.setenv("DEV_EMAIL_SHORTCUTS", "false")
        response = anon_client.post("/auth/request-code/", json={"email": test_user.email})
        assert "dev_code" not in response.json()


class TestEmailCaseInsensitivity:
    """Emails are stored and matched lowercase — the local part included,
    which EmailStr alone leaves untouched."""

    def test_register_stores_email_lowercase(self, anon_client):
        response = _register(anon_client, email="Mixed.Case@Example.com")
        assert response.status_code == 201
        assert response.json()["email"] == "mixed.case@example.com"

    def test_register_rejects_case_variant_of_existing_email(self, anon_client, test_user):
        response = _register(anon_client, email=test_user.email.upper())
        assert response.status_code == 400
        assert response.json()["detail"] == "Email already registered"

    def test_sign_in_with_different_case_succeeds(self, anon_client, test_user, sent_codes):
        anon_client.post("/auth/request-code/", json={"email": "TestUser@Example.COM"})
        response = _verify(anon_client, "TESTUSER@example.com", sent_codes[test_user.email])
        assert response.status_code == 200

    def test_case_variants_share_one_code_send_limit(self, anon_client, test_user):
        from src.db.repositories.rate_limit import MAX_LOGIN_CODE_EMAIL_ATTEMPTS
        variants = ["testuser@example.com", "TestUser@example.com", "TESTUSER@example.com",
                    "testUser@example.com", "Testuser@example.com", "TestUSER@example.com"]
        assert len(variants) > MAX_LOGIN_CODE_EMAIL_ATTEMPTS
        for email in variants:
            response = anon_client.post("/auth/request-code/", json={"email": email})
        assert response.status_code == 429

    def test_repository_lookup_is_case_insensitive(self, db_session, test_user):
        from src.db.repositories.users import get_user_by_email
        assert get_user_by_email(db_session, "TESTUSER@EXAMPLE.COM").id == test_user.id


class TestRemovedPasswordEndpoints:
    @pytest.mark.parametrize("path", [
        "/auth/login/", "/auth/forgot-password/", "/auth/reset-password/",
        "/auth/change-password/", "/auth/resend-verification/",
    ])
    def test_post_endpoint_is_gone(self, anon_client, path):
        assert anon_client.post(path, json={}).status_code in (404, 405)

    def test_verify_email_link_is_gone(self, anon_client):
        assert anon_client.get("/auth/verify-email/?token=abc").status_code in (404, 405)


class TestLogout:
    def test_logout_returns_200(self, client):
        response = client.post("/auth/logout/")
        assert response.status_code == 200

    def test_logout_clears_cookie(self, client, anon_client):
        client.post("/auth/logout/")
        response = client.post("/auth/logout/")
        assert response.status_code == 200
        data = response.json()
        assert data["logged_out"] is True


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
        for i in range(MAX_REGISTER_ATTEMPTS):
            _register(anon_client, email=f"r{i}@example.com")
        response = _register(anon_client, email="one-more@example.com")
        assert response.status_code == 429

    def test_register_not_blocked_before_limit(self, anon_client):
        from src.db.repositories.rate_limit import MAX_REGISTER_ATTEMPTS
        for i in range(MAX_REGISTER_ATTEMPTS - 1):
            _register(anon_client, email=f"u{i}@x.com")
        response = _register(anon_client, email="last@x.com")
        assert response.status_code != 429

    def test_localhost_not_limited_outside_production(self, anon_client, test_user, monkeypatch):
        """Local E2E runs register and sign in repeatedly from 127.0.0.1."""
        from src.db.repositories.rate_limit import MAX_LOGIN_CODE_EMAIL_ATTEMPTS
        monkeypatch.setattr("src.routers.auth._client_ip", lambda request: "127.0.0.1")
        for _ in range(MAX_LOGIN_CODE_EMAIL_ATTEMPTS + 2):
            response = anon_client.post("/auth/request-code/", json={"email": test_user.email})
        assert response.status_code == 200

    def test_localhost_still_limited_in_production(self, monkeypatch):
        from src.routers.auth import _rate_limits_apply
        monkeypatch.setattr("src.routers.auth.is_prod", lambda: True)
        assert _rate_limits_apply("127.0.0.1") is True
        assert _rate_limits_apply("::1") is True

    def test_code_requests_blocked_after_limit(self, anon_client, test_user):
        from src.db.repositories.rate_limit import MAX_LOGIN_CODE_EMAIL_ATTEMPTS
        for _ in range(MAX_LOGIN_CODE_EMAIL_ATTEMPTS):
            assert anon_client.post("/auth/request-code/", json={"email": test_user.email}).status_code == 200
        response = anon_client.post("/auth/request-code/", json={"email": test_user.email})
        assert response.status_code == 429

    def test_code_limit_is_per_email(self, anon_client, test_user):
        from src.db.repositories.rate_limit import MAX_LOGIN_CODE_EMAIL_ATTEMPTS
        for _ in range(MAX_LOGIN_CODE_EMAIL_ATTEMPTS):
            anon_client.post("/auth/request-code/", json={"email": test_user.email})
        response = anon_client.post("/auth/request-code/", json={"email": "other@example.com"})
        assert response.status_code == 200

    def test_unknown_emails_count_against_the_limit_too(self, anon_client):
        """Otherwise a 429 for one address and not another would reveal which
        one has an account."""
        from src.db.repositories.rate_limit import MAX_LOGIN_CODE_EMAIL_ATTEMPTS
        for _ in range(MAX_LOGIN_CODE_EMAIL_ATTEMPTS):
            anon_client.post("/auth/request-code/", json={"email": "nobody@example.com"})
        response = anon_client.post("/auth/request-code/", json={"email": "nobody@example.com"})
        assert response.status_code == 429

    def test_registration_codes_share_the_per_email_limit(self, anon_client):
        from src.db.repositories.rate_limit import MAX_LOGIN_CODE_EMAIL_ATTEMPTS
        for _ in range(MAX_LOGIN_CODE_EMAIL_ATTEMPTS):
            _register(anon_client, email="spam-me@example.com")
        response = anon_client.post("/auth/request-code/", json={"email": "spam-me@example.com"})
        assert response.status_code == 429

    def test_per_ip_limit_across_many_addresses(self, anon_client):
        from src.db.repositories.rate_limit import MAX_LOGIN_CODE_IP_ATTEMPTS
        for i in range(MAX_LOGIN_CODE_IP_ATTEMPTS):
            anon_client.post("/auth/request-code/", json={"email": f"spray{i}@example.com"})
        response = anon_client.post("/auth/request-code/", json={"email": "fresh@example.com"})
        assert response.status_code == 429


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
