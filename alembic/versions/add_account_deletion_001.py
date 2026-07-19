"""Add account deletion grace period support

Revision ID: add_account_deletion_001
Revises: clean_stopword_terms_001
Create Date: 2026-07-19
"""
from alembic import op

revision = 'add_account_deletion_001'
down_revision = 'clean_stopword_terms_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS deletion_scheduled_at TIMESTAMPTZ
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS account_deletion_tokens (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_account_deletion_tokens_user_id ON account_deletion_tokens (user_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS account_deletion_tokens")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS deletion_scheduled_at")
