"""Add model_name column to messages

Revision ID: add_model_name_to_messages_001
Revises: add_rate_limit_entries_001
Create Date: 2026-07-14
"""
from alembic import op

revision = 'add_model_name_to_messages_001'
down_revision = 'add_rate_limit_entries_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE messages
        ADD COLUMN IF NOT EXISTS model_name VARCHAR(100)
    """)


def downgrade() -> None:
    op.drop_column('messages', 'model_name')
