import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import uuid

from src.db.repositories.users import create_user, get_user_by_email, get_user_by_id, update_last_login, count_all_users
from src.db.repositories.waitlist import create_waitlist_entry, list_waitlist_entries, count_waitlist_entries
from src.db.repositories.conversations import (
    create_conversation, get_conversation_by_id, soft_delete_conversation, get_conversations_list_by_user_id
)
from src.db.repositories.messeges import add_message, get_recent_messages, get_messages_by_conversation_id
from src.db.repositories.password_resets import create_reset_token, verify_reset_token, consume_reset_token
from src.auth.security import SecurityUtils


class TestUserRepository:
    def test_create_user_returns_user_with_id(self, db_session):
        user = create_user(
            db_session,
            first_name="Alice", last_name="A",
            email="alice@example.com",
            password_hash=SecurityUtils.hash_password("AlicePass123"),
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
            password_hash=SecurityUtils.hash_password("BobPass123"),
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

    def test_count_all_users(self, db_session, test_user):
        assert count_all_users(db_session) == 1
        create_user(
            db_session,
            first_name="Second", last_name="User",
            email="second@example.com",
            password_hash=SecurityUtils.hash_password("SecondPass123"),
        )
        assert count_all_users(db_session) == 2


class TestWaitlistRepository:
    def test_create_waitlist_entry_returns_entry_with_id(self, db_session):
        entry = create_waitlist_entry(db_session, "new@example.com")
        assert entry.id is not None
        assert entry.email == "new@example.com"
        assert entry.invited is False

    def test_create_waitlist_entry_is_idempotent(self, db_session):
        first = create_waitlist_entry(db_session, "dupe@example.com")
        second = create_waitlist_entry(db_session, "dupe@example.com")
        assert first.id == second.id
        assert count_waitlist_entries(db_session) == 1

    def test_list_waitlist_entries_orders_oldest_first(self, db_session):
        create_waitlist_entry(db_session, "first@example.com")
        create_waitlist_entry(db_session, "second@example.com")
        entries = list_waitlist_entries(db_session)
        emails = [e.email for e in entries]
        assert emails.index("first@example.com") < emails.index("second@example.com")

    def test_count_waitlist_entries(self, db_session):
        assert count_waitlist_entries(db_session) == 0
        create_waitlist_entry(db_session, "counted@example.com")
        assert count_waitlist_entries(db_session) == 1


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


class TestPasswordResetRepository:
    def test_create_reset_token_returns_url_safe_string(self, db_session, test_user):
        token = create_reset_token(db_session, test_user.id)
        assert isinstance(token, str)
        assert len(token) > 20  # secrets.token_urlsafe(32) → ~43 chars

    def test_create_reset_token_invalidates_previous_token(self, db_session, test_user):
        token1 = create_reset_token(db_session, test_user.id)
        db_session.commit()
        create_reset_token(db_session, test_user.id)
        db_session.commit()
        # token1 was deleted when token2 was created
        record, _ = verify_reset_token(db_session, token1)
        assert record is None

    def test_verify_reset_token_success(self, db_session, test_user):
        token = create_reset_token(db_session, test_user.id)
        db_session.commit()

        record, msg = verify_reset_token(db_session, token)
        assert record is not None
        assert msg == ""
        assert str(record.user_id) == str(test_user.id)

    def test_verify_reset_token_wrong_token(self, db_session, test_user):
        create_reset_token(db_session, test_user.id)
        db_session.commit()

        record, msg = verify_reset_token(db_session, "completely-wrong-token")
        assert record is None
        assert "invalid" in msg.lower()

    def test_verify_reset_token_max_uses_blocks(self, db_session, test_user):
        token = create_reset_token(db_session, test_user.id)
        db_session.commit()

        # Exhaust uses by calling consume_reset_token 5 times
        for _ in range(5):
            record, _ = verify_reset_token(db_session, token)
            assert record is not None
            record.use_count += 1
            db_session.commit()

        record, msg = verify_reset_token(db_session, token)
        assert record is None
        assert "too many" in msg.lower()

    def test_verify_reset_token_expired(self, db_session, test_user):
        from freezegun import freeze_time
        with freeze_time("2026-01-01 12:00:00"):
            token = create_reset_token(db_session, test_user.id)
            db_session.commit()

        # Move forward past the 60-minute TTL
        with freeze_time("2026-01-01 13:30:00"):
            record, msg = verify_reset_token(db_session, token)

        assert record is None
        assert "expir" in msg.lower()

    def test_consume_reset_token_marks_used_and_increments(self, db_session, test_user):
        token = create_reset_token(db_session, test_user.id)
        db_session.commit()

        record, _ = verify_reset_token(db_session, token)
        assert record is not None
        consume_reset_token(db_session, record)

        # After consuming, token is no longer valid
        record2, msg = verify_reset_token(db_session, token)
        assert record2 is None
        assert "invalid" in msg.lower() or "used" in msg.lower()

    def test_verify_reset_token_not_reusable_after_consume(self, db_session, test_user):
        token = create_reset_token(db_session, test_user.id)
        db_session.commit()

        record, _ = verify_reset_token(db_session, token)
        consume_reset_token(db_session, record)

        record2, msg = verify_reset_token(db_session, token)
        assert record2 is None
