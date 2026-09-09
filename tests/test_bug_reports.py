"""Tests for POST /bug-reports/ (src/routers/bug_reports.py) — covers both
report_type values ('bug', the default, and 'feedback')."""
from src.db.models import BugReport


class TestCreateBugReport:
    def test_defaults_to_bug_type(self, client, db_session, test_user):
        res = client.post("/bug-reports/", json={"title": "Something broke"})
        assert res.status_code == 200
        report = db_session.query(BugReport).filter(BugReport.user_id == test_user.id).one()
        assert report.report_type == "bug"

    def test_feedback_type_persisted(self, client, db_session, test_user):
        res = client.post("/bug-reports/", json={
            "title": "Love the new reranker",
            "description": "Answers feel much more relevant now.",
            "report_type": "feedback",
        })
        assert res.status_code == 200
        report = db_session.query(BugReport).filter(BugReport.user_id == test_user.id).one()
        assert report.report_type == "feedback"
        assert report.description == "Answers feel much more relevant now."

    def test_invalid_report_type_rejected(self, client):
        res = client.post("/bug-reports/", json={"title": "x", "report_type": "not-a-type"})
        assert res.status_code == 422

    def test_title_required_for_feedback_too(self, client):
        res = client.post("/bug-reports/", json={"title": "   ", "report_type": "feedback"})
        assert res.status_code == 422

    def test_how_to_reproduce_optional_for_feedback(self, client, db_session, test_user):
        res = client.post("/bug-reports/", json={"title": "Just saying hi", "report_type": "feedback"})
        assert res.status_code == 200
        report = db_session.query(BugReport).filter(BugReport.user_id == test_user.id).one()
        assert report.how_to_reproduce is None
