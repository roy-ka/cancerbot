"""Tests for the optional user health-profile feature: CRUD via /profile/*,
its cascade on account deletion, and /auth/check/'s needs_onboarding flag."""
import pytest

from src.db.models import UserProfile


class TestGetProfile:
    def test_no_profile_returns_exists_false(self, client):
        response = client.get("/profile/me")
        assert response.status_code == 200
        assert response.json() == {"exists": False}

    def test_unauthenticated_returns_401(self, anon_client):
        response = anon_client.get("/profile/me")
        assert response.status_code == 401


class TestUpdateProfile:
    def test_skip_with_empty_body_creates_row(self, client, test_user, db_session):
        response = client.put("/profile/me", json={})
        assert response.status_code == 200
        assert response.json()["exists"] is True

        db_session.expire_all()
        profile = db_session.query(UserProfile).filter(UserProfile.user_id == test_user.id).first()
        assert profile is not None
        assert profile.cancer_type is None

    def test_save_populates_fields(self, client):
        response = client.put(
            "/profile/me",
            json={
                "cancer_type": "Glioblastoma",
                "stage": "IV",
                "biomarkers": "IDH-wildtype, MGMT-unmethylated",
                "age_band": "40_64",
                "treatment_status": "in_active_treatment",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["cancer_type"] == "Glioblastoma"
        assert data["age_band"] == "40_64"
        assert data["treatment_status"] == "in_active_treatment"

    def test_invalid_age_band_rejected(self, client):
        response = client.put("/profile/me", json={"age_band": "ancient"})
        assert response.status_code == 422

    def test_invalid_treatment_status_rejected(self, client):
        response = client.put("/profile/me", json={"treatment_status": "cured_forever"})
        assert response.status_code == 422

    def test_empty_string_age_band_accepted_as_unset(self, client):
        """The frontend's <Select> "Prefer not to say" option submits ""
        rather than omitting the field — this must not 422, or saving the
        onboarding form with those left at their default fails outright."""
        response = client.put(
            "/profile/me",
            json={"cancer_type": "Glioblastoma", "age_band": "", "treatment_status": ""},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["age_band"] is None
        assert data["treatment_status"] is None
        assert data["cancer_type"] == "Glioblastoma"

    def test_partial_update_does_not_clear_other_fields(self, client):
        client.put("/profile/me", json={"cancer_type": "Glioblastoma", "stage": "IV"})
        response = client.put("/profile/me", json={"stage": "III"})
        assert response.status_code == 200
        data = response.json()
        assert data["cancer_type"] == "Glioblastoma"
        assert data["stage"] == "III"

    def test_explicit_empty_string_clears_a_field(self, client):
        client.put("/profile/me", json={"cancer_type": "Glioblastoma"})
        response = client.put("/profile/me", json={"cancer_type": ""})
        assert response.status_code == 200
        assert response.json()["cancer_type"] is None

    def test_chronic_is_a_valid_treatment_status(self, client):
        response = client.put("/profile/me", json={"treatment_status": "chronic"})
        assert response.status_code == 200
        assert response.json()["treatment_status"] == "chronic"


class TestClearProfile:
    def test_delete_removes_the_row(self, client, test_user, db_session):
        client.put("/profile/me", json={"cancer_type": "Glioblastoma"})
        response = client.delete("/profile/me")
        assert response.status_code == 200

        db_session.expire_all()
        assert db_session.query(UserProfile).filter(UserProfile.user_id == test_user.id).first() is None

    def test_delete_when_no_profile_is_a_no_op(self, client):
        response = client.delete("/profile/me")
        assert response.status_code == 200


class TestOnboardingFlag:
    def test_needs_onboarding_true_when_no_profile(self, client):
        response = client.get("/auth/check/")
        assert response.json()["needs_onboarding"] is True

    def test_needs_onboarding_false_after_skip(self, client):
        client.put("/profile/me", json={})
        response = client.get("/auth/check/")
        assert response.json()["needs_onboarding"] is False

    def test_needs_onboarding_false_after_save(self, client):
        client.put("/profile/me", json={"cancer_type": "Glioblastoma"})
        response = client.get("/auth/check/")
        assert response.json()["needs_onboarding"] is False

    def test_needs_onboarding_true_again_after_clearing(self, client):
        client.put("/profile/me", json={"cancer_type": "Glioblastoma"})
        client.delete("/profile/me")
        response = client.get("/auth/check/")
        assert response.json()["needs_onboarding"] is True


class TestCascadeOnAccountDeletion:
    def test_profile_deleted_when_user_deleted(self, db_session, test_user):
        from src.db.repositories.users import delete_user
        from src.db.repositories.profile import upsert_profile

        upsert_profile(db_session, test_user.id, cancer_type="Glioblastoma")
        assert db_session.query(UserProfile).filter(UserProfile.user_id == test_user.id).first() is not None

        delete_user(db_session, test_user.id)

        assert db_session.query(UserProfile).filter(UserProfile.user_id == test_user.id).first() is None


class TestRenderProfileRecall:
    """render_profile_recall builds the personal-question fast-path answer
    directly from saved profile fields — deliberately NOT LLM-generated, so
    it can never blend a factual recall of "what you told us" with a
    generated medical claim. See OllamaConnector.classify_personal_question
    and its use in conversations.py."""

    def test_populated_field_is_recited(self, db_session, test_user):
        from src.db.repositories.profile import upsert_profile, render_profile_recall

        profile = upsert_profile(db_session, test_user.id, cancer_type="Glioblastoma")
        text = render_profile_recall(profile, ["cancer_type"])
        assert "Glioblastoma" in text
        assert "saved cancer type" in text

    def test_categorical_fields_use_display_labels(self, db_session, test_user):
        from src.db.repositories.profile import upsert_profile, render_profile_recall

        profile = upsert_profile(
            db_session, test_user.id, age_band="40_64", treatment_status="in_active_treatment",
        )
        text = render_profile_recall(profile, ["age_band", "treatment_status"])
        assert "40-64" in text
        assert "in active treatment" in text

    def test_empty_field_says_not_saved(self, db_session, test_user):
        from src.db.repositories.profile import upsert_profile, render_profile_recall

        profile = upsert_profile(db_session, test_user.id, cancer_type="Glioblastoma")
        text = render_profile_recall(profile, ["stage"])
        assert "haven't saved your stage" in text
        assert "account menu" in text

    def test_none_profile_treated_as_all_empty(self):
        from src.db.repositories.profile import render_profile_recall

        text = render_profile_recall(None, ["cancer_type"])
        assert "haven't saved" in text

    def test_untracked_ask_appends_honest_gap_note(self, db_session, test_user):
        from src.db.repositories.profile import upsert_profile, render_profile_recall

        profile = upsert_profile(db_session, test_user.id, cancer_type="Glioblastoma")
        text = render_profile_recall(profile, [], has_untracked_ask=True)
        assert "doesn't track that specific detail" in text

    def test_unknown_field_name_is_ignored(self, db_session, test_user):
        from src.db.repositories.profile import upsert_profile, render_profile_recall

        profile = upsert_profile(db_session, test_user.id, cancer_type="Glioblastoma")
        text = render_profile_recall(profile, ["cancer_type", "not_a_real_field"])
        assert text.count("saved") == 1
