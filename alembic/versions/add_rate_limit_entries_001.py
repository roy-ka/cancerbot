"""Add rate_limit_entries table for register and forgot-password throttling

Revision ID: add_rate_limit_entries_001
Revises: add_token_version_to_users_001
Create Date: 2026-07-09
"""
from alembic import op

revision = 'add_rate_limit_entries_001'
down_revision = 'add_token_version_to_users_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS rate_limit_entries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key VARCHAR(320) NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            blocked_until TIMESTAMPTZ,
            last_attempt_at TIMESTAMPTZ,
            CONSTRAINT uq_rate_limit_key UNIQUE (key)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_rate_limit_entries_key ON rate_limit_entries (key)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rate_limit_entries")
