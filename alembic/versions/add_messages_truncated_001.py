"""Add messages.truncated — flags an assistant answer cut short by
GROQ_MAX_TOKENS, so the frontend can offer a Continue action and the flag
survives reopening the conversation.

Revision ID: add_messages_truncated_001
Revises: drop_users_is_ninja_001
Create Date: 2026-09-05
"""
from alembic import op

revision = 'add_messages_truncated_001'
down_revision = 'drop_users_is_ninja_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS truncated BOOLEAN NOT NULL DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS truncated")
