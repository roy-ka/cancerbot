"""Tests for src/db/repositories/tokens.py's atomic consume — the fix for a
TOCTOU race where two concurrent requests for the same token could both
pass a plain "used_at IS NULL" read and both complete their side effect
(schedule deletion twice, swap email twice).
_consume_token is now an UPDATE ... WHERE used_at IS NULL, so only one
concurrent caller can ever see it return True for a given token."""
from src.db.repositories.tokens import (
    create_deletion_request_token,
    verify_deletion_token,
    consume_deletion_token,
    create_email_change_request_token,
    verify_email_change_request_token,
    consume_email_change_request_token,
    create_email_change_token,
    verify_email_change_token,
    consume_email_change_token,
    create_email_revert_token,
    verify_email_revert_token,
    consume_email_revert_token,
)


class TestAtomicConsume:
    """For each token type: the first consume call wins (True), and a
    second call for the exact same token — simulating a request that lost
    the race — gets False instead of silently re-succeeding."""

    def test_deletion_token(self, db_session, test_user):
        token = create_deletion_request_token(db_session, test_user.id)
        record, _ = verify_deletion_token(db_session, token)
        assert consume_deletion_token(db_session, record) is True
        db_session.commit()
        assert consume_deletion_token(db_session, record) is False

    def test_email_change_request_token(self, db_session, test_user):
        token = create_email_change_request_token(db_session, test_user.id)
        record, _ = verify_email_change_request_token(db_session, token)
        assert consume_email_change_request_token(db_session, record) is True
        db_session.commit()
        assert consume_email_change_request_token(db_session, record) is False

    def test_email_change_token(self, db_session, test_user):
        token = create_email_change_token(db_session, test_user.id, "new@example.com")
        record, _ = verify_email_change_token(db_session, token)
        assert consume_email_change_token(db_session, record) is True
        db_session.commit()
        assert consume_email_change_token(db_session, record) is False

    def test_email_revert_token(self, db_session, test_user):
        token = create_email_revert_token(db_session, test_user.id, "old@example.com")
        record, _ = verify_email_revert_token(db_session, token)
        assert consume_email_revert_token(db_session, record) is True
        db_session.commit()
        assert consume_email_revert_token(db_session, record) is False

    def test_two_in_flight_verify_calls_only_one_consume_wins(self, db_session, test_user):
        """The realistic race: both requests verify (peek) before either
        consumes — this is the actual scenario the fix targets, not just
        sequential reuse after a commit."""
        token = create_email_change_request_token(db_session, test_user.id)
        record_a, error_a = verify_email_change_request_token(db_session, token)
        record_b, error_b = verify_email_change_request_token(db_session, token)
        assert record_a is not None and error_a == ""
        assert record_b is not None and error_b == ""

        assert consume_email_change_request_token(db_session, record_a) is True
        db_session.commit()
        assert consume_email_change_request_token(db_session, record_b) is False
