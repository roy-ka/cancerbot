"""Add share_token to conversations (public read-only sharing)

Revision ID: add_conversation_share_token_001
Revises: add_bug_report_type_001
Create Date: 2026-09-10
"""
from alembic import op

revision = 'add_conversation_share_token_001'
down_revision = 'add_bug_report_type_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE conversations
        ADD COLUMN IF NOT EXISTS share_token VARCHAR(64) UNIQUE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_conversations_share_token ON conversations (share_token)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_conversations_share_token")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS share_token")
