"""Tests for the ninja-only admin flow: browse users -> browse their
conversations -> post a message that's hidden from the real user.

The ninja account has no users row at all — its credentials are checked
directly against NINJA_EMAIL/NINJA_PASSWORD (see src/routers/auth.py's
_ninja_login and src/deps/auth.py's get_current_ninja_user). conftest.py's
NINJA_EMAIL/NINJA_PASSWORD env vars back both the real-login tests below
and the `ninja_client` fixture (which stubs get_current_ninja_user directly
rather than logging in for real, for tests that don't care about login
itself)."""
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock

from src.auth.security import SecurityUtils

NINJA_EMAIL = os.environ["NINJA_EMAIL"]
NINJA_PASSWORD = os.environ["NINJA_PASSWORD"]

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


class TestNinjaLogin:
    """Ninja logs in through the normal /auth/login/ endpoint, but against
    NINJA_EMAIL/NINJA_PASSWORD directly — there's no users row to check a
    password hash against."""

    def test_correct_credentials_succeed(self, anon_client):
        response = anon_client.post(
            "/auth/login/", json={"email": NINJA_EMAIL, "password": NINJA_PASSWORD, "rememberMe": False},
        )
        assert response.status_code == 200
        assert response.json()["is_ninja"] is True
        assert "access_token" in response.cookies

    def test_wrong_password_rejected(self, anon_client):
        response = anon_client.post(
            "/auth/login/", json={"email": NINJA_EMAIL, "password": "WrongPassword!", "rememberMe": False},
        )
        assert response.status_code == 401

    def test_wrong_password_locks_out_after_max_attempts(self, anon_client):
        from src.db.repositories.login_attempts import MAX_LOGIN_ATTEMPTS
        for _ in range(MAX_LOGIN_ATTEMPTS):
            anon_client.post(
                "/auth/login/", json={"email": NINJA_EMAIL, "password": "WrongPassword!", "rememberMe": False},
            )
        locked = anon_client.post(
            "/auth/login/", json={"email": NINJA_EMAIL, "password": NINJA_PASSWORD, "rememberMe": False},
        )
        assert locked.status_code == 429

    def test_regular_user_email_falls_through_to_normal_login(self, anon_client, test_user):
        """A non-ninja email must never be handled by the ninja branch —
        confirms _ninja_login's email check actually gates on NINJA_EMAIL."""
        response = anon_client.post(
            "/auth/login/", json={"email": test_user.email, "password": "TestPass123!", "rememberMe": False},
        )
        assert response.status_code == 200
        assert response.json()["is_ninja"] is False

    def test_token_expires_in_two_hours(self, anon_client):
        """A privileged account should never get the long-lived sessions
        regular login flows allow (rememberMe, or the dev-only 1-year
        override)."""
        response = anon_client.post(
            "/auth/login/", json={"email": NINJA_EMAIL, "password": NINJA_PASSWORD, "rememberMe": True},
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

    def test_logged_in_ninja_token_rejected_by_regular_get_current_user_route(self, anon_client):
        """Ninja can no longer use the app as a regular chat user — its JWT
        carries a sentinel subject that matches no real users row, so a
        get_current_user-gated route must reject it cleanly (401), not
        crash trying to look it up."""
        login = anon_client.post(
            "/auth/login/", json={"email": NINJA_EMAIL, "password": NINJA_PASSWORD, "rememberMe": False},
        )
        assert login.status_code == 200
        response = anon_client.get("/auth/check/")
        assert response.status_code == 401


class TestNinjaAuthorization:
    def test_regular_user_forbidden_from_ninja_routes(self, real_token_client):
        response = real_token_client.get("/ninja/users/")
        assert response.status_code == 403

    def test_ninja_user_allowed(self, ninja_client):
        response = ninja_client.get("/ninja/users/")
        assert response.status_code == 200

    def test_anon_user_unauthorized(self, anon_client):
        response = anon_client.get("/ninja/users/")
        assert response.status_code == 401


class TestNinjaCheckEndpoint:
    def test_ninja_authenticated(self, ninja_client):
        response = ninja_client.get("/ninja/check/")
        assert response.status_code == 200
        assert response.json()["authenticated"] is True

    def test_regular_user_forbidden(self, real_token_client):
        response = real_token_client.get("/ninja/check/")
        assert response.status_code == 403

    def test_anon_unauthorized(self, anon_client):
        response = anon_client.get("/ninja/check/")
        assert response.status_code == 401


class TestListUsers:
    def test_lists_all_users_including_non_ninja(self, ninja_client, test_user):
        response = ninja_client.get("/ninja/users/")
        assert response.status_code == 200
        emails = [u["email"] for u in response.json()["users"]]
        assert test_user.email in emails

    def test_returns_first_and_last_name(self, ninja_client, test_user):
        response = ninja_client.get("/ninja/users/")
        row = next(u for u in response.json()["users"] if u["email"] == test_user.email)
        assert row["first_name"] == test_user.first_name
        assert row["last_name"] == test_user.last_name
        assert "name" not in row
class TestListUserConversations:
    def test_lists_target_users_conversations(self, ninja_client, test_user, test_conversation):
        response = ninja_client.get(f"/ninja/users/{test_user.id}/conversations/")
        assert response.status_code == 200
        conv_ids = [c["id"] for c in response.json()["conversations"]]
        assert str(test_conversation.id) in conv_ids


class TestNinjaMessagesHiddenFromRealUser:
    def test_ninja_message_not_visible_to_real_user(self, ninja_client, real_token_client, test_conversation):
        post_resp = ninja_client.post(
            f"/ninja/conversations/{test_conversation.id}/add_message",
            json={"content": "Is this response accurate?"},
        )
        assert post_resp.status_code == 200

        # The real user's own endpoint must never show the ninja exchange
        user_resp = real_token_client.get(f"/conversations/{test_conversation.id}/messages/")
        assert user_resp.status_code == 200
        contents = [m["content"] for m in user_resp.json()["messages"]]
        assert "Is this response accurate?" not in contents
        assert _DEFAULT_STREAM_CONTENT not in contents

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

    def test_ninja_can_post_into_conversation_it_does_not_own(self, ninja_client, test_conversation):
        response = ninja_client.post(
            f"/ninja/conversations/{test_conversation.id}/add_message",
            json={"content": "Checking on behalf of support"},
        )
        assert response.status_code == 200

    def test_regular_user_cannot_post_via_ninja_route(self, real_token_client, test_conversation):
        response = real_token_client.post(
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
