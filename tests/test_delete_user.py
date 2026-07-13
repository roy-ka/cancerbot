import pytest
from src.db import models


def _delete(client, password: str):
    return client.request("DELETE", "/auth/user/", json={"password": password})


class TestDeleteUser:
    def test_success_deletes_user(self, client, test_user, db_session):
        user_id = test_user.id  # capture before expire_all detaches the object
        response = _delete(client, "TestPass123!")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

        db_session.expire_all()
        user = db_session.query(models.User).filter(models.User.id == user_id).first()
        assert user is None

    def test_success_clears_cookie(self, client):
        response = _delete(client, "TestPass123!")
        assert response.status_code == 200
        assert "access_token" in response.headers.get("set-cookie", "")

    def test_wrong_password_returns_401(self, client):
        response = _delete(client, "WrongPassword!")
        assert response.status_code == 401

    def test_unauthenticated_returns_401(self, anon_client):
        response = anon_client.request("DELETE", "/auth/user/", json={"password": "TestPass123!"})
        assert response.status_code == 401

    def test_cascades_delete_conversations(self, client, test_conversation, db_session):
        conv_id = test_conversation.id
        _delete(client, "TestPass123!")

        db_session.expire_all()
        conv = db_session.query(models.Conversation).filter(models.Conversation.id == conv_id).first()
        assert conv is None
