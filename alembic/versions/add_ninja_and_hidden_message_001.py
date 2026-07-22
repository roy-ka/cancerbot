"""Add is_ninja to users and hidden_from_user to messages

Revision ID: add_ninja_and_hidden_message_001
Revises: add_bug_reports_table_001
Create Date: 2026-07-22
"""
from alembic import op

revision = 'add_ninja_and_hidden_message_001'
down_revision = 'add_account_deletion_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS is_ninja BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        ALTER TABLE messages
        ADD COLUMN IF NOT EXISTS hidden_from_user BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_messages_hidden_from_user ON messages (hidden_from_user)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_hidden_from_user")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS hidden_from_user")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_ninja")
