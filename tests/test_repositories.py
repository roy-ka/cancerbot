import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import uuid

from src.db.repositories.users import create_user, get_user_by_email, get_user_by_id, update_last_login
from src.db.repositories.conversations import (
    create_conversation, get_conversation_by_id, soft_delete_conversation, get_conversations_list_by_user_id
)
from src.db.repositories.messeges import add_message, get_recent_messages, get_messages_by_conversation_id
from src.db.repositories.password_resets import create_reset_code, verify_and_consume_code
from src.auth.security import SecurityUtils


class TestUserRepository:
    def test_create_user_returns_user_with_id(self, db_session):
        user = create_user(
            db_session,
            name="Alice",
            email="alice@example.com",
            password_hash=SecurityUtils.hash_password("AlicePass123"),
        )
        assert user.id is not None
        assert user.name == "Alice"
        assert user.email == "alice@example.com"

    def test_create_user_persists_in_db(self, db_session):
        user = create_user(
            db_session,
            name="Bob",
            email="bob@example.com",
            password_hash=SecurityUtils.hash_password("BobPass123"),
        )
        db_session.commit()
        fetched = get_user_by_email(db_session, "bob@example.com")
        assert fetched.id == user.id
        assert fetched.name == "Bob"

    def test_get_user_by_email_returns_existing_user(self, db_session, test_user):
        found = get_user_by_email(db_session, test_user.email)
        assert found.id == test_user.id
        assert found.name == test_user.name

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
        assert msg.sources_ids == "src-001,src-002"

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


class TestPasswordResetRepository:
    def test_create_reset_code_returns_six_digit_string(self, db_session, test_user):
        code = create_reset_code(db_session, test_user.id)
        assert isinstance(code, str)
        assert code.isdigit()
        assert len(code) == 6

    def test_create_reset_code_invalidates_previous_code(self, db_session, test_user):
        code1 = create_reset_code(db_session, test_user.id)
        db_session.commit()
        code2 = create_reset_code(db_session, test_user.id)
        db_session.commit()
        # code1 should be marked as used or expired, code2 should be valid
        ok, _ = verify_and_consume_code(db_session, test_user.id, code1)
        assert ok is False

    def test_verify_and_consume_code_success(self, db_session, test_user):
        code = create_reset_code(db_session, test_user.id)
        db_session.commit()

        # Mock datetime to be before expiry
        naive_now = datetime(2026, 1, 1, 12, 0, 0)
        with patch("src.db.repositories.password_resets.datetime") as mock_dt:
            mock_dt.now.return_value = naive_now
            ok, msg = verify_and_consume_code(db_session, test_user.id, code)

        assert ok is True
        assert msg == ""

    def test_verify_and_consume_code_wrong_code(self, db_session, test_user):
        create_reset_code(db_session, test_user.id)
        db_session.commit()

        naive_now = datetime(2026, 1, 1, 12, 0, 0)
        with patch("src.db.repositories.password_resets.datetime") as mock_dt:
            mock_dt.now.return_value = naive_now
            ok, msg = verify_and_consume_code(db_session, test_user.id, "999999")

        assert ok is False
        assert "attempt" in msg.lower()

    def test_verify_and_consume_code_max_attempts_blocks(self, db_session, test_user):
        code = create_reset_code(db_session, test_user.id)
        db_session.commit()

        naive_now = datetime(2026, 1, 1, 12, 0, 0)
        with patch("src.db.repositories.password_resets.datetime") as mock_dt:
            mock_dt.now.return_value = naive_now
            for _ in range(5):
                verify_and_consume_code(db_session, test_user.id, "wrong")
            db_session.commit()
            ok, msg = verify_and_consume_code(db_session, test_user.id, code)

        assert ok is False
        assert "exceeded" in msg.lower() or "locked" in msg.lower() or "blocked" in msg.lower()

    def test_verify_and_consume_code_expired(self, db_session, test_user):
        code = create_reset_code(db_session, test_user.id)
        db_session.commit()

        # Mock datetime to be AFTER expiry
        naive_now = datetime(2026, 1, 1, 23, 0, 0)  # 15+ minutes later
        with patch("src.db.repositories.password_resets.datetime") as mock_dt:
            mock_dt.now.return_value = naive_now
            ok, msg = verify_and_consume_code(db_session, test_user.id, code)

        assert ok is False
        assert "expir" in msg.lower()

    def test_verify_and_consume_code_not_reusable(self, db_session, test_user):
        code = create_reset_code(db_session, test_user.id)
        db_session.commit()

        naive_now = datetime(2026, 1, 1, 12, 0, 0)
        with patch("src.db.repositories.password_resets.datetime") as mock_dt:
            mock_dt.now.return_value = naive_now
            ok, _ = verify_and_consume_code(db_session, test_user.id, code)
        assert ok is True

        with patch("src.db.repositories.password_resets.datetime") as mock_dt:
            mock_dt.now.return_value = naive_now
            ok, msg = verify_and_consume_code(db_session, test_user.id, code)

        assert ok is False
        assert "already used" in msg.lower() or "invalid" in msg.lower()
