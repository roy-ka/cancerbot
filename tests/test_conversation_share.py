"""Tests for conversation sharing: POST/DELETE /conversations/{id}/share
(owner-only) and GET /shared/{token} (public, unauthenticated)."""
import uuid

from src.db.repositories.conversations import create_conversation
from src.db.repositories.messeges import add_message
from src.db.models import Conversation


class TestShareConversation:
    def test_enable_share_returns_a_token_and_url(self, client, test_conversation):
        res = client.post(f"/conversations/{test_conversation.id}/share")
        assert res.status_code == 200
        data = res.json()
        assert data["share_token"]
        assert data["share_url"].endswith(f"/s/{data['share_token']}")

    def test_enable_share_is_idempotent(self, client, test_conversation):
        first = client.post(f"/conversations/{test_conversation.id}/share").json()
        second = client.post(f"/conversations/{test_conversation.id}/share").json()
        assert first["share_token"] == second["share_token"]

    def test_disable_share_revokes_the_token(self, client, db_session, test_conversation):
        client.post(f"/conversations/{test_conversation.id}/share")
        res = client.delete(f"/conversations/{test_conversation.id}/share")
        assert res.status_code == 200

        db_session.expire_all()
        conv = db_session.query(Conversation).filter(Conversation.id == test_conversation.id).one()
        assert conv.share_token is None

    def test_share_404_for_conversation_owned_by_someone_else(self, client):
        res = client.post(f"/conversations/{uuid.uuid4()}/share")
        assert res.status_code == 404

    def test_unshare_404_for_conversation_owned_by_someone_else(self, client):
        res = client.delete(f"/conversations/{uuid.uuid4()}/share")
        assert res.status_code == 404

    def test_conversation_messages_reports_shared_state(self, client, test_conversation):
        before = client.get(f"/conversations/{test_conversation.id}/messages/").json()
        assert before["conversation"]["shared"] is False

        client.post(f"/conversations/{test_conversation.id}/share")
        after = client.get(f"/conversations/{test_conversation.id}/messages/").json()
        assert after["conversation"]["shared"] is True


class TestPublicSharedConversation:
    def test_returns_title_and_non_hidden_messages(self, anon_client, client, db_session, test_conversation):
        add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="Cancer is...")
        add_message(
            db_session, conversation_id=test_conversation.id, role="assistant",
            content="Ninja-only reply", hidden_from_user=True,
        )
        db_session.commit()

        token = client.post(f"/conversations/{test_conversation.id}/share").json()["share_token"]

        res = anon_client.get(f"/shared/{token}")
        assert res.status_code == 200
        data = res.json()
        assert data["conversation"]["title"] == test_conversation.title
        contents = [m["content"] for m in data["messages"]]
        assert "Cancer is..." in contents
        assert "Ninja-only reply" not in contents

    def test_404_for_unknown_token(self, anon_client):
        res = anon_client.get("/shared/not-a-real-token")
        assert res.status_code == 404

    def test_404_after_revoke(self, anon_client, client, test_conversation):
        token = client.post(f"/conversations/{test_conversation.id}/share").json()["share_token"]
        client.delete(f"/conversations/{test_conversation.id}/share")

        res = anon_client.get(f"/shared/{token}")
        assert res.status_code == 404

    def test_404_for_deleted_conversation(self, anon_client, client, db_session, test_user):
        conv = create_conversation(db_session, user_id=test_user.id, title="Throwaway")
        db_session.commit()
        token = client.post(f"/conversations/{conv.id}/share").json()["share_token"]

        client.delete(f"/conversations/{conv.id}")

        res = anon_client.get(f"/shared/{token}")
        assert res.status_code == 404

    def test_no_owner_info_leaked(self, anon_client, client, test_conversation):
        token = client.post(f"/conversations/{test_conversation.id}/share").json()["share_token"]
        res = anon_client.get(f"/shared/{token}")
        data = res.json()
        assert "user_id" not in data["conversation"]
        assert "id" not in data["conversation"]
