import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import uuid

from src.db.repositories.users import (
    create_user, get_user_by_email, get_user_by_id, update_last_login,
)
from src.db.repositories.conversations import (
    create_conversation, get_conversation_by_id, soft_delete_conversation, get_conversations_list_by_user_id
)
from src.db.repositories.messeges import (
    add_message, get_recent_messages, get_messages_by_conversation_id,
    get_messages_up_to, copy_messages,
)
from src.db.repositories.message_feedback import set_feedback, get_feedback_for_messages
from src.db.repositories.tokens import (
    create_login_code, verify_login_code, LOGIN_CODE_MAX_ATTEMPTS,
)


class TestUserRepository:
    def test_create_user_returns_user_with_id(self, db_session):
        user = create_user(
            db_session,
            first_name="Alice", last_name="A",
            email="alice@example.com",
        )
        assert user.id is not None
        assert user.first_name == "Alice"
        assert user.last_name == "A"
        assert user.email == "alice@example.com"

    def test_create_user_persists_in_db(self, db_session):
        user = create_user(
            db_session,
            first_name="Bob", last_name="B",
            email="bob@example.com",
        )
        db_session.commit()
        fetched = get_user_by_email(db_session, "bob@example.com")
        assert fetched.id == user.id
        assert fetched.first_name == "Bob"

    def test_get_user_by_email_returns_existing_user(self, db_session, test_user):
        found = get_user_by_email(db_session, test_user.email)
        assert found.id == test_user.id
        assert found.first_name == test_user.first_name

    def test_get_user_by_email_returns_none_for_missing(self, db_session):
        found = get_user_by_email(db_session, "nonexistent@example.com")
        assert found is None

    def test_get_user_by_id_returns_user(self, db_session, test_user):
        found = get_user_by_id(db_session, test_user.id)
        assert found.email == test_user.email

    def test_get_user_by_id_returns_none_for_missing(self, db_session):
        fake_id = uuid.uuid4()
        found = get_user_by_id(db_session, fake_id)
        assert found is None

    def test_update_last_login(self, db_session, test_user):
        update_last_login(db_session, test_user)
        db_session.refresh(test_user)
        assert test_user.last_login is not None
class TestConversationRepository:
    def test_create_conversation_returns_conversation(self, db_session, test_user):
        conv = create_conversation(db_session, user_id=test_user.id, title="Test Conversation")
        assert conv.id is not None
        assert conv.user_id == test_user.id
        assert conv.title == "Test Conversation"

    def test_soft_delete_conversation_sets_deleted_at(self, db_session, test_user):
        conv = create_conversation(db_session, user_id=test_user.id, title="ToDelete")
        db_session.commit()
        result = soft_delete_conversation(db_session, conv.id, test_user.id)
        assert result is True
        db_session.refresh(conv)
        assert conv.deleted_at is not None

    def test_soft_delete_conversation_returns_false_for_wrong_user(self, db_session, test_user):
        conv = create_conversation(db_session, user_id=test_user.id, title="TestConv")
        db_session.commit()
        other_user_id = uuid.uuid4()
        result = soft_delete_conversation(db_session, conv.id, other_user_id)
        assert result is False

    def test_soft_delete_conversation_returns_false_for_missing(self, db_session, test_user):
        fake_conv_id = uuid.uuid4()
        result = soft_delete_conversation(db_session, fake_conv_id, test_user.id)
        assert result is False

    def test_get_conversation_by_id_returns_none_when_soft_deleted(self, db_session, test_user):
        conv = create_conversation(db_session, user_id=test_user.id, title="ToDelete")
        db_session.commit()
        soft_delete_conversation(db_session, conv.id, test_user.id)
        db_session.commit()
        found = get_conversation_by_id(db_session, test_user, conv.id)
        assert found is None

    def test_get_conversations_list_returns_conversations(self, db_session, test_user):
        create_conversation(db_session, user_id=test_user.id, title="Conv1")
        create_conversation(db_session, user_id=test_user.id, title="Conv2")
        db_session.commit()
        convs = get_conversations_list_by_user_id(db_session, test_user.id, limit=10)
        assert len(convs) >= 2

    def test_get_conversations_list_excludes_deleted(self, db_session, test_user):
        conv1 = create_conversation(db_session, user_id=test_user.id, title="Conv1")
        conv2 = create_conversation(db_session, user_id=test_user.id, title="Conv2")
        db_session.commit()
        soft_delete_conversation(db_session, conv1.id, test_user.id)
        db_session.commit()
        convs = get_conversations_list_by_user_id(db_session, test_user.id, limit=10)
        titles = [c.title for c in convs]
        assert "Conv2" in titles
        assert "Conv1" not in titles


class TestMessageRepository:
    def test_add_message_user_message(self, db_session, test_conversation):
        msg = add_message(
            db_session,
            conversation_id=test_conversation.id,
            role="user",
            content="What is cancer?",
        )
        assert msg.role == "user"
        assert msg.content == "What is cancer?"
        assert msg.conversation_id == test_conversation.id

    def test_add_message_assistant_message(self, db_session, test_conversation):
        msg = add_message(
            db_session,
            conversation_id=test_conversation.id,
            role="assistant",
            content="Cancer is...",
            sources_ids="src-001,src-002",
        )
        assert msg.role == "assistant"
        assert msg.sources_ids == ["src-001", "src-002"]

    def test_get_recent_messages(self, db_session, test_conversation):
        add_message(db_session, conversation_id=test_conversation.id, role="user", content="msg1")
        add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="msg2")
        db_session.commit()
        recent = get_recent_messages(db_session, test_conversation.id, limit=10)
        assert len(recent) >= 3  # original + 2 new

    def test_get_recent_messages_respects_limit(self, db_session, test_conversation):
        for i in range(5):
            add_message(db_session, conversation_id=test_conversation.id, role="user", content=f"msg{i}")
        db_session.commit()
        recent = get_recent_messages(db_session, test_conversation.id, limit=2)
        assert len(recent) == 2


class TestMessageFeedbackRepository:
    def test_set_feedback_creates_vote(self, db_session, test_conversation):
        msg = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="answer")
        result = set_feedback(db_session, message_id=msg.id, user_id=test_conversation.user_id, vote=1)
        assert result == 1

    def test_set_feedback_same_vote_toggles_off(self, db_session, test_conversation):
        msg = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="answer")
        set_feedback(db_session, message_id=msg.id, user_id=test_conversation.user_id, vote=1)
        result = set_feedback(db_session, message_id=msg.id, user_id=test_conversation.user_id, vote=1)
        assert result is None

    def test_set_feedback_different_vote_switches(self, db_session, test_conversation):
        msg = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="answer")
        set_feedback(db_session, message_id=msg.id, user_id=test_conversation.user_id, vote=1)
        result = set_feedback(db_session, message_id=msg.id, user_id=test_conversation.user_id, vote=-1)
        assert result == -1

    def test_get_feedback_for_messages_bulk(self, db_session, test_conversation):
        msg1 = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="a1")
        msg2 = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="a2")
        set_feedback(db_session, message_id=msg1.id, user_id=test_conversation.user_id, vote=1)
        set_feedback(db_session, message_id=msg2.id, user_id=test_conversation.user_id, vote=-1)

        result = get_feedback_for_messages(db_session, [msg1.id, msg2.id], test_conversation.user_id)
        assert result == {str(msg1.id): 1, str(msg2.id): -1}

    def test_get_feedback_for_messages_omits_unvoted(self, db_session, test_conversation):
        msg = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="a1")
        result = get_feedback_for_messages(db_session, [msg.id], test_conversation.user_id)
        assert result == {}

    def test_get_feedback_for_messages_empty_list(self, db_session, test_conversation):
        assert get_feedback_for_messages(db_session, [], test_conversation.user_id) == {}


class TestConversationSplitRepository:
    def test_get_messages_up_to_includes_target_and_earlier(self, db_session, test_conversation):
        # test_conversation fixture already has one user message
        assistant_msg = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="a1")
        add_message(db_session, conversation_id=test_conversation.id, role="user", content="q2")

        result = get_messages_up_to(db_session, test_conversation.id, assistant_msg.id)
        assert [m.content for m in result] == ["What is cancer?", "a1"]

    def test_get_messages_up_to_excludes_hidden(self, db_session, test_conversation):
        add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="hidden", hidden_from_user=True)
        target = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="visible")

        result = get_messages_up_to(db_session, test_conversation.id, target.id)
        assert [m.content for m in result] == ["What is cancer?", "visible"]

    def test_get_messages_up_to_missing_message_returns_empty(self, db_session, test_conversation):
        import uuid
        result = get_messages_up_to(db_session, test_conversation.id, uuid.uuid4())
        assert result == []

    def test_copy_messages_creates_new_rows_in_dest_conversation(self, db_session, test_conversation):
        dest = create_conversation(db_session, user_id=test_conversation.user_id, title="dest")
        source_messages = get_messages_up_to(
            db_session, test_conversation.id,
            add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="a1").id,
        )
        copies = copy_messages(db_session, source_messages, dest.id)

        assert len(copies) == len(source_messages)
        assert all(c.conversation_id == dest.id for c in copies)
        assert [c.content for c in copies] == [m.content for m in source_messages]
        # Originals untouched
        assert all(m.conversation_id == test_conversation.id for m in source_messages)

    def test_copy_messages_preserves_order(self, db_session, test_conversation):
        dest = create_conversation(db_session, user_id=test_conversation.user_id, title="dest")
        add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="a1")
        last = add_message(db_session, conversation_id=test_conversation.id, role="user", content="q2")
        source_messages = get_messages_up_to(db_session, test_conversation.id, last.id)

        copies = copy_messages(db_session, source_messages, dest.id)
        ordered = sorted(copies, key=lambda m: m.created_at)
        assert [m.content for m in ordered] == [m.content for m in source_messages]


class TestLoginCodeRepository:
    EMAIL = "testuser@example.com"

    def test_code_is_six_digits(self, db_session, test_user):
        code = create_login_code(db_session, self.EMAIL, user_id=test_user.id)
        assert len(code) == 6 and code.isdigit()

    def test_correct_code_verifies_and_is_single_use(self, db_session, test_user):
        code = create_login_code(db_session, self.EMAIL, user_id=test_user.id)
        record, error = verify_login_code(db_session, self.EMAIL, code)
        assert error == ""
        assert str(record.user_id) == str(test_user.id)
        db_session.commit()

        record2, error2 = verify_login_code(db_session, self.EMAIL, code)
        assert record2 is None
        assert "invalid" in error2.lower()

    def test_new_code_replaces_the_previous_one(self, db_session, test_user):
        first = create_login_code(db_session, self.EMAIL, user_id=test_user.id)
        second = create_login_code(db_session, self.EMAIL, user_id=test_user.id)
        if first == second:
            return  # 1-in-a-million collision; nothing to distinguish
        record, _ = verify_login_code(db_session, self.EMAIL, first)
        assert record is None
        record, _ = verify_login_code(db_session, self.EMAIL, second)
        assert record is not None

    def test_wrong_code_reports_remaining_attempts(self, db_session, test_user):
        code = create_login_code(db_session, self.EMAIL, user_id=test_user.id)
        wrong = "000000" if code != "000000" else "111111"
        record, error = verify_login_code(db_session, self.EMAIL, wrong)
        assert record is None
        assert f"{LOGIN_CODE_MAX_ATTEMPTS - 1} attempt(s) left" in error

    def test_code_dies_after_max_attempts_even_if_then_correct(self, db_session, test_user):
        code = create_login_code(db_session, self.EMAIL, user_id=test_user.id)
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(LOGIN_CODE_MAX_ATTEMPTS):
            verify_login_code(db_session, self.EMAIL, wrong)
        record, error = verify_login_code(db_session, self.EMAIL, code)
        assert record is None
        assert "too many" in error.lower()

    def test_expired_code_is_rejected(self, db_session, test_user):
        from freezegun import freeze_time
        with freeze_time("2026-01-01 12:00:00"):
            code = create_login_code(db_session, self.EMAIL, user_id=test_user.id)
        with freeze_time("2026-01-01 12:11:00"):
            record, error = verify_login_code(db_session, self.EMAIL, code)
        assert record is None
        assert "expired" in error.lower()

    def test_code_is_bound_to_its_address(self, db_session, test_user):
        code = create_login_code(db_session, self.EMAIL, user_id=test_user.id)
        record, _ = verify_login_code(db_session, "someone-else@example.com", code)
        assert record is None

    def test_code_is_not_stored_in_plain_or_as_plain_sha256(self, db_session, test_user):
        """A plain SHA-256 of six digits is reversible by trying all million
        — the stored value must be keyed (HMAC with JWT_SECRET)."""
        import hashlib
        from src.db.models import Token
        code = create_login_code(db_session, self.EMAIL, user_id=test_user.id)
        stored = db_session.query(Token).filter(Token.target_email == self.EMAIL).one().token_hash
        assert code not in stored
        assert stored != hashlib.sha256(code.encode()).hexdigest()
        assert stored != hashlib.sha256(f"{self.EMAIL}:{code}".encode()).hexdigest()

    def test_ninja_code_has_no_user(self, db_session):
        code = create_login_code(db_session, "ninja-test@example.com")
        record, error = verify_login_code(db_session, "ninja-test@example.com", code)
        assert error == ""
        assert record.user_id is None


class TestTokenTypeIsolation:
    """The merged `tokens` table stores every token type with plain
    string secrets.token_urlsafe(32) values — nothing about the token
    string itself reveals its type. A missing token_type filter anywhere in
    tokens.py would let, say, a deletion link be accepted as an email-change
    link, which is the specific bug this class exists to catch."""

    def test_deletion_token_does_not_verify_as_email_change_request(self, db_session, test_user):
        from src.db.repositories.tokens import create_deletion_request_token, verify_email_change_request_token

        deletion_token = create_deletion_request_token(db_session, test_user.id)
        record, error = verify_email_change_request_token(db_session, deletion_token)
        assert record is None
        assert "invalid" in error.lower()

    def test_creating_one_type_does_not_invalidate_another_type_for_same_user(self, db_session, test_user):
        """create_*_token deletes the user's prior unused tokens of *that
        same type* — it must not also wipe out the user's tokens of a
        different type, login codes included."""
        from src.db.repositories.tokens import create_deletion_request_token, verify_deletion_token

        deletion_token = create_deletion_request_token(db_session, test_user.id)
        create_login_code(db_session, test_user.email, user_id=test_user.id)

        record, error = verify_deletion_token(db_session, deletion_token)
        assert record is not None
        assert error == ""

    def test_verify_deletion_token_locks_the_row(self, db_session, test_user):
        """verify_deletion_token must request SELECT ... FOR UPDATE so a
        second concurrent /confirm-delete/ call for the same token blocks
        until the first transaction commits, instead of both racing past
        the used_at IS NULL check — see _verify_token's for_update param."""
        from src.db.repositories import tokens as tokens_repo

        deletion_token = tokens_repo.create_deletion_request_token(db_session, test_user.id)
        db_session.commit()

        with patch.object(tokens_repo, "_verify_token", wraps=tokens_repo._verify_token) as spy:
            tokens_repo.verify_deletion_token(db_session, deletion_token)

        assert spy.call_args.kwargs.get("for_update") is True
