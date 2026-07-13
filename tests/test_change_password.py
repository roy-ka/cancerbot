import pytest
from src.auth.security import SecurityUtils


class TestChangePassword:
    def test_success_updates_password(self, client, test_user, db_session):
        response = client.post(
            "/auth/change-password/",
            json={"current_password": "TestPass123!", "new_password": "NewPass456@"},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

        db_session.expire_all()
        db_session.refresh(test_user)
        assert SecurityUtils.verify_password("NewPass456@", test_user.password_hash)

    def test_success_increments_token_version(self, client, test_user, db_session):
        version_before = test_user.token_version or 1
        client.post(
            "/auth/change-password/",
            json={"current_password": "TestPass123!", "new_password": "NewPass456@"},
        )
        db_session.expire_all()
        db_session.refresh(test_user)
        assert test_user.token_version == version_before + 1

    def test_wrong_current_password_returns_401(self, client):
        response = client.post(
            "/auth/change-password/",
            json={"current_password": "WrongPass!", "new_password": "NewPass456@"},
        )
        assert response.status_code == 401

    def test_weak_new_password_returns_400(self, client):
        response = client.post(
            "/auth/change-password/",
            json={"current_password": "TestPass123!", "new_password": "weak"},
        )
        assert response.status_code == 400

    def test_unauthenticated_returns_401(self, anon_client):
        response = anon_client.post(
            "/auth/change-password/",
            json={"current_password": "TestPass123!", "new_password": "NewPass456@"},
        )
        assert response.status_code == 401
