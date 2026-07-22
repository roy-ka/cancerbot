"""Tests for the ninja-only admin flow: browse users -> browse their
conversations -> post a message that's hidden from the real user."""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock

from src.auth.security import SecurityUtils


_DEFAULT_STREAM_CONTENT = "Cancer cells exhibit the Warburg effect."


def _make_stream(content: str):
    async def _gen(*args, **kwargs):
        yield content
        yield {}
    return _gen


@pytest.fixture(autouse=True)
def mock_external_services(mock_retrieval):
    with (
        patch("src.routers.conversations.run_retrieval", return_value=mock_retrieval),
        patch(
            "src.routers.conversations.OllamaConnector.stream_text",
            new=_make_stream(_DEFAULT_STREAM_CONTENT),
        ),
        patch(
            "src.routers.conversations.search_and_embed",
            new=AsyncMock(return_value={
                "indexed": 0, "skipped": 0, "terms": [],
                "pubmed_found": 0, "crossref_found": 0, "wikipedia_found": 0,
            }),
        ),
    ):
        yield


class TestNinjaAuthorization:
    def test_regular_user_forbidden_from_ninja_routes(self, client):
        response = client.get("/ninja/users/")
        assert response.status_code == 403

    def test_ninja_user_allowed(self, ninja_client, test_user):
        response = ninja_client.get("/ninja/users/")
        assert response.status_code == 200

    def test_anon_user_unauthorized(self, anon_client):
        response = anon_client.get("/ninja/users/")
        assert response.status_code == 401


class TestNinjaCheckAuthExposesFlag:
    def test_regular_user_is_ninja_false(self, client):
        response = client.get("/auth/check/")
        assert response.json()["is_ninja"] is False

    def test_ninja_user_is_ninja_true(self, ninja_client):
        response = ninja_client.get("/auth/check/")
        assert response.json()["is_ninja"] is True


class TestListUsers:
    def test_lists_all_users_including_non_ninja(self, ninja_client, test_user):
        response = ninja_client.get("/ninja/users/")
        assert response.status_code == 200
        emails = [u["email"] for u in response.json()["users"]]
        assert test_user.email in emails


class TestListUserConversations:
    def test_lists_target_users_conversations(self, ninja_client, test_user, test_conversation):
        response = ninja_client.get(f"/ninja/users/{test_user.id}/conversations/")
        assert response.status_code == 200
        conv_ids = [c["id"] for c in response.json()["conversations"]]
        assert str(test_conversation.id) in conv_ids


class TestNinjaMessagesHiddenFromRealUser:
    def test_ninja_message_not_visible_to_real_user(
        self, TestingSessionLocal, test_ninja_user, test_user, test_conversation
    ):
        # app.dependency_overrides is global on the shared `app` object, so
        # ninja_client + client fixtures can't be used together in one test
        # (whichever is set up last wins for both clients) — switch the
        # current-user override explicitly between the ninja and real-user
        # calls instead.
        from fastapi.testclient import TestClient
        from src.main import app
        from src.deps.db import get_db
        from src.deps.auth import get_current_user
        from src.db import models

        def override_get_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        def _as(user_email):
            def _override():
                db = TestingSessionLocal()
                u = db.query(models.User).filter(models.User.email == user_email).first()
                db.close()
                return u
            return _override

        app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(app) as c:
                app.dependency_overrides[get_current_user] = _as(test_ninja_user.email)
                post_resp = c.post(
                    f"/ninja/conversations/{test_conversation.id}/add_message",
                    json={"content": "Is this response accurate?"},
                )
                assert post_resp.status_code == 200

                # The real user's own endpoint must never show the ninja exchange
                app.dependency_overrides[get_current_user] = _as(test_user.email)
                user_resp = c.get(f"/conversations/{test_conversation.id}/messages/")
                assert user_resp.status_code == 200
                contents = [m["content"] for m in user_resp.json()["messages"]]
                assert "Is this response accurate?" not in contents
                assert _DEFAULT_STREAM_CONTENT not in contents
        finally:
            app.dependency_overrides.clear()

    def test_ninja_sees_own_hidden_message_in_ninja_view(self, ninja_client, test_conversation):
        ninja_client.post(
            f"/ninja/conversations/{test_conversation.id}/add_message",
            json={"content": "Is this response accurate?"},
        )

        ninja_resp = ninja_client.get(f"/ninja/conversations/{test_conversation.id}/messages/")
        assert ninja_resp.status_code == 200
        contents = [m["content"] for m in ninja_resp.json()["messages"]]
        assert "Is this response accurate?" in contents
        hidden_flags = {m["content"]: m["hidden_from_user"] for m in ninja_resp.json()["messages"]}
        assert hidden_flags["Is this response accurate?"] is True

    def test_ninja_can_post_into_conversation_it_does_not_own(self, ninja_client, test_conversation, test_ninja_user):
        assert str(test_conversation.user_id) != str(test_ninja_user.id)
        response = ninja_client.post(
            f"/ninja/conversations/{test_conversation.id}/add_message",
            json={"content": "Checking on behalf of support"},
        )
        assert response.status_code == 200

    def test_regular_user_cannot_post_via_ninja_route(self, client, test_conversation):
        response = client.post(
            f"/ninja/conversations/{test_conversation.id}/add_message",
            json={"content": "trying anyway"},
        )
        assert response.status_code == 403

    def test_ninja_posting_first_message_does_not_trigger_title_generation(
        self, ninja_client, db_session, test_user
    ):
        """A hidden ninja message must never change what the real user sees
        in their conversation list — including the title — even if it's
        literally the first message ever posted into a brand-new conversation."""
        from src.db.repositories.conversations import create_conversation

        conv = create_conversation(db_session, user_id=test_user.id, title="Untouched Title")
        db_session.commit()

        with patch(
            "src.routers.conversations.OllamaConnector.generate_title", new_callable=AsyncMock
        ) as mock_generate_title:
            response = ninja_client.post(
                f"/ninja/conversations/{conv.id}/add_message",
                json={"content": "Ninja's very first message here"},
            )
            assert response.status_code == 200
            mock_generate_title.assert_not_awaited()

        assert response.json()["conversation"]["title"] == "Untouched Title"


class TestNinjaLoginExpiry:
    """A privileged account should never get the long-lived sessions regular
    login flows allow (rememberMe, or the dev-only 1-year override)."""

    def test_ninja_login_token_expires_in_two_hours(self, anon_client, test_ninja_user):
        response = anon_client.post(
            "/auth/login/",
            json={"email": test_ninja_user.email, "password": "NinjaPass123!", "rememberMe": True},
        )
        assert response.status_code == 200
        token = response.cookies.get("access_token") or anon_client.cookies.get("access_token")
        payload = SecurityUtils.decode_jwt_token(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        delta = exp - datetime.now(timezone.utc)
        assert delta.total_seconds() < 2 * 3600 + 60  # allow a little slack
        assert delta.total_seconds() > 2 * 3600 - 60

    def test_regular_user_login_not_capped_at_two_hours(self, anon_client, test_user):
        response = anon_client.post(
            "/auth/login/",
            json={"email": test_user.email, "password": "TestPass123!", "rememberMe": True},
        )
        assert response.status_code == 200
        token = response.cookies.get("access_token") or anon_client.cookies.get("access_token")
        payload = SecurityUtils.decode_jwt_token(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        delta = exp - datetime.now(timezone.utc)
        assert delta.total_seconds() > 2 * 3600  # rememberMe/dev override grants far more than 2h


class TestEnsureNinjaUser:
    """Unit tests for src.main._ensure_ninja_user — the idempotent startup hook."""

    def test_creates_ninja_when_missing(self, db_session, monkeypatch):
        from src.main import _ensure_ninja_user
        from src.db.repositories.users import get_user_by_email

        monkeypatch.setenv("NINJA_EMAIL", "brandnew-ninja@example.com")
        monkeypatch.setenv("NINJA_PASSWORD", "SomePass123!")
        with patch("src.db.session.SessionLocal", return_value=db_session):
            _ensure_ninja_user()

        user = get_user_by_email(db_session, "brandnew-ninja@example.com")
        assert user is not None
        assert user.is_ninja is True
        assert user.email_verified is True

    def test_noop_when_env_vars_missing(self, db_session, monkeypatch):
        from src.main import _ensure_ninja_user
        from src.db.repositories.users import get_user_by_email

        monkeypatch.delenv("NINJA_EMAIL", raising=False)
        monkeypatch.delenv("NINJA_PASSWORD", raising=False)
        with patch("src.db.session.SessionLocal", return_value=db_session):
            _ensure_ninja_user()

        assert get_user_by_email(db_session, "brandnew-ninja@example.com") is None

    def test_idempotent_when_already_exists(self, db_session, monkeypatch):
        from src.main import _ensure_ninja_user
        from src.db.repositories.users import create_user
        from src.db.models import User

        create_user(
            db_session, name="Ninja", email="existing-ninja@example.com",
            password_hash=SecurityUtils.hash_password("Whatever123!"),
        )
        monkeypatch.setenv("NINJA_EMAIL", "existing-ninja@example.com")
        monkeypatch.setenv("NINJA_PASSWORD", "Whatever123!")
        with patch("src.db.session.SessionLocal", return_value=db_session):
            _ensure_ninja_user()
            _ensure_ninja_user()  # calling twice must not error or duplicate

        users = db_session.query(User).filter_by(email="existing-ninja@example.com").all()
        assert len(users) == 1
        assert users[0].is_ninja is True
