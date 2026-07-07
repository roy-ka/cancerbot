"""Add email verification

Revision ID: add_email_verification_001
Revises: repair_add_urls_to_messages_001
Create Date: 2026-07-07
"""
from alembic import op

revision = 'add_email_verification_001'
down_revision = 'repair_add_urls_to_messages_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE")
    # Mark all existing users as verified so they aren't locked out
    op.execute("UPDATE users SET email_verified = TRUE WHERE email_verified = FALSE")
    op.execute("""
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_email_verification_tokens_user_id
        ON email_verification_tokens (user_id)
    """)


def downgrade() -> None:
    op.drop_table('email_verification_tokens')
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email_verified")
