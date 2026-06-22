"""Add bug_reports table

Revision ID: add_bug_reports_table_001
Revises: cleanup_message_columns_001
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'add_bug_reports_table_001'
down_revision = 'cleanup_message_columns_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS bug_reports (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            how_to_reproduce TEXT,
            created_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_bug_reports_user_id ON bug_reports (user_id)
    """)


def downgrade() -> None:
    op.drop_table('bug_reports')
