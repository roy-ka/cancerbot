"""Add message_feedback table and conversation fork lineage columns

Revision ID: message_options_001
Revises: waitlist_invite_token_001
Create Date: 2026-09-03
"""
from alembic import op

revision = 'message_options_001'
down_revision = 'waitlist_invite_token_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS message_feedback (
            id UUID PRIMARY KEY,
            message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            vote INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_message_feedback_message_user UNIQUE (message_id, user_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_message_feedback_message_id ON message_feedback (message_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_message_feedback_user_id ON message_feedback (user_id)")

    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS forked_from_conversation_id UUID")
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS forked_from_message_id UUID")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversations_forked_from_conversation_id "
        "ON conversations (forked_from_conversation_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_conversations_forked_from_conversation_id")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS forked_from_message_id")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS forked_from_conversation_id")
    op.execute("DROP TABLE IF EXISTS message_feedback")
