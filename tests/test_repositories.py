import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import uuid

from src.db.repositories.users import (
    create_user, get_user_by_email, get_user_by_id, update_last_login, count_all_users,
    email_variation_is_registered,
)
from src.utils.email_normalize import normalize_email_for_dedup
from src.db.repositories.waitlist import create_waitlist_entry, list_waitlist_entries, count_waitlist_entries
from src.db.repositories.conversations import (
    create_conversation, get_conversation_by_id, soft_delete_conversation, get_conversations_list_by_user_id
)
from src.db.repositories.messeges import (
    add_message, get_recent_messages, get_messages_by_conversation_id,
    get_messages_up_to, copy_messages,
)
from src.db.repositories.message_feedback import set_feedback, get_feedback_for_messages
from src.db.repositories.tokens import (
    create_reset_token, verify_reset_token, consume_reset_token,
    create_waitlist_invite_token, verify_waitlist_invite_token,
)
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

    def test_email_variation_is_registered_true_for_gmail_dot_variation(self, db_session):
        create_user(
            db_session,
            first_name="Ada", last_name="L",
            email="ada.lovelace@gmail.com",
            password_hash=SecurityUtils.hash_password("Pass1234"),
        )
        assert email_variation_is_registered(
            db_session, normalize_email_for_dedup("adalovelace@gmail.com")
        ) is True

    def test_email_variation_is_registered_false_for_unregistered(self, db_session, test_user):
        assert email_variation_is_registered(
            db_session, normalize_email_for_dedup("nobody@example.com")
        ) is False


class TestWaitlistRepository:
    def test_create_waitlist_entry_returns_entry_with_id(self, db_session):
        entry = create_waitlist_entry(db_session, "new@example.com", "New Person")
        assert entry.id is not None
        assert entry.email == "new@example.com"
        assert entry.name == "New Person"
        assert entry.invited is False

    def test_create_waitlist_entry_is_idempotent(self, db_session):
        first = create_waitlist_entry(db_session, "dupe@example.com", "First Name")
        second = create_waitlist_entry(db_session, "dupe@example.com", "Second Name")
        assert first.id == second.id
        assert second.name == "First Name"
        assert count_waitlist_entries(db_session) == 1

    def test_create_waitlist_entry_stores_normalized_email(self, db_session):
        entry = create_waitlist_entry(db_session, "John.Doe+promo@Gmail.com", "John Doe")
        assert entry.normalized_email == "johndoe@gmail.com"
        assert entry.email == "John.Doe+promo@Gmail.com"

    def test_create_waitlist_entry_dedupes_gmail_dot_variation(self, db_session):
        first = create_waitlist_entry(db_session, "john.doe@gmail.com", "John")
        second = create_waitlist_entry(db_session, "johndoe@gmail.com", "John Again")
        assert first.id == second.id
        assert count_waitlist_entries(db_session) == 1

    def test_create_waitlist_entry_dedupes_plus_tag_variation(self, db_session):
        first = create_waitlist_entry(db_session, "user@example.com", "User")
        second = create_waitlist_entry(db_session, "user+newsletter@example.com", "User Again")
        assert first.id == second.id
        assert count_waitlist_entries(db_session) == 1

    def test_create_waitlist_entry_dedupes_case_variation(self, db_session):
        first = create_waitlist_entry(db_session, "case@example.com", "Case")
        second = create_waitlist_entry(db_session, "Case@Example.com", "Case Again")
        assert first.id == second.id
        assert count_waitlist_entries(db_session) == 1

    def test_list_waitlist_entries_orders_oldest_first(self, db_session):
        create_waitlist_entry(db_session, "first@example.com", "First")
        create_waitlist_entry(db_session, "second@example.com", "Second")
        entries = list_waitlist_entries(db_session)
        emails = [e.email for e in entries]
        assert emails.index("first@example.com") < emails.index("second@example.com")

    def test_count_waitlist_entries(self, db_session):
        assert count_waitlist_entries(db_session) == 0
        create_waitlist_entry(db_session, "counted@example.com", "Counted")
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


class TestTokenTypeIsolation:
    """The merged `tokens` table stores all three token types with plain
    string secrets.token_urlsafe(32) values — nothing about the token
    string itself reveals its type. A missing token_type filter anywhere in
    tokens.py would let a password-reset token be accepted as an email
    verification link (or vice versa), which is the specific bug this
    class exists to catch."""

    def test_reset_token_does_not_verify_as_verification_token(self, db_session, test_user):
        from src.db.repositories.tokens import verify_and_consume_token

        reset_token = create_reset_token(db_session, test_user.id)
        db_session.commit()

        user_id, error = verify_and_consume_token(db_session, reset_token)
        assert user_id is None
        assert "invalid" in error.lower()

    def test_verification_token_does_not_verify_as_reset_token(self, db_session, test_user):
        from src.db.repositories.tokens import create_verification_token

        verification_token = create_verification_token(db_session, test_user.id)
        db_session.commit()

        record, error = verify_reset_token(db_session, verification_token)
        assert record is None
        assert "invalid" in error.lower()

    def test_deletion_token_does_not_verify_as_reset_token(self, db_session, test_user):
        from src.db.repositories.tokens import create_deletion_request_token

        deletion_token = create_deletion_request_token(db_session, test_user.id)
        db_session.commit()

        record, error = verify_reset_token(db_session, deletion_token)
        assert record is None
        assert "invalid" in error.lower()

    def test_creating_one_type_does_not_invalidate_another_type_for_same_user(self, db_session, test_user):
        """create_*_token deletes the user's prior unused tokens of *that
        same type* — it must not also wipe out the user's tokens of a
        different type."""
        from src.db.repositories.tokens import create_verification_token

        reset_token = create_reset_token(db_session, test_user.id)
        db_session.commit()
        create_verification_token(db_session, test_user.id)
        db_session.commit()

        record, error = verify_reset_token(db_session, reset_token)
        assert record is not None
        assert error == ""

    def test_password_reset_use_count_does_not_affect_other_types(self, db_session, test_user):
        """use_count tracking is specific to password_reset — consuming a
        deletion or verification token must not increment it in a way that
        could ever trip password reset's max-uses check."""
        from src.db.repositories.tokens import create_deletion_request_token, verify_deletion_token, consume_deletion_token

        deletion_token = create_deletion_request_token(db_session, test_user.id)
        db_session.commit()
        record, _ = verify_deletion_token(db_session, deletion_token)
        consume_deletion_token(db_session, record)
        db_session.commit()

        assert record.use_count == 0


class TestWaitlistInviteToken:
    def test_create_and_verify_round_trip(self, db_session):
        entry = create_waitlist_entry(db_session, "invite@example.com", "Invite Person")
        token = create_waitlist_invite_token(db_session, entry.id)

        record, error = verify_waitlist_invite_token(db_session, token, "invite@example.com")
        assert record is not None
        assert error == ""
        assert record.waitlist_entry_id == entry.id
        assert record.user_id is None

    def test_verify_wrong_email_rejected(self, db_session):
        entry = create_waitlist_entry(db_session, "owner@example.com", "Owner")
        token = create_waitlist_invite_token(db_session, entry.id)

        record, error = verify_waitlist_invite_token(db_session, token, "someone-else@example.com")
        assert record is None
        assert "different email" in error.lower()

    def test_verify_accepts_email_variation(self, db_session):
        entry = create_waitlist_entry(db_session, "john.doe@gmail.com", "John")
        token = create_waitlist_invite_token(db_session, entry.id)

        record, error = verify_waitlist_invite_token(db_session, token, "johndoe+tag@gmail.com")
        assert record is not None
        assert error == ""

    def test_resend_invalidates_previous_token(self, db_session):
        entry = create_waitlist_entry(db_session, "resend2@example.com", "Resend")
        token1 = create_waitlist_invite_token(db_session, entry.id)
        token2 = create_waitlist_invite_token(db_session, entry.id)

        record1, error1 = verify_waitlist_invite_token(db_session, token1, "resend2@example.com")
        assert record1 is None

        record2, error2 = verify_waitlist_invite_token(db_session, token2, "resend2@example.com")
        assert record2 is not None
        assert error2 == ""

    def test_expired_invite_token_rejected(self, db_session):
        from freezegun import freeze_time

        entry = create_waitlist_entry(db_session, "expired@example.com", "Expired")
        with freeze_time("2026-01-01 12:00:00"):
            token = create_waitlist_invite_token(db_session, entry.id)

        with freeze_time("2026-01-03 13:00:00"):  # 49h later
            record, error = verify_waitlist_invite_token(db_session, token, "expired@example.com")

        assert record is None
        assert "expired" in error.lower()

    def test_invite_token_does_not_verify_as_reset_token(self, db_session):
        entry = create_waitlist_entry(db_session, "notreset@example.com", "Not Reset")
        invite_token = create_waitlist_invite_token(db_session, entry.id)

        record, error = verify_reset_token(db_session, invite_token)
        assert record is None
