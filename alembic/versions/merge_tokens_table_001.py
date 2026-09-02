"""Merge password_reset_codes, email_verification_tokens, and
account_deletion_tokens into one tokens table

Revision ID: merge_tokens_table_001
Revises: waitlist_email_norm_001
Create Date: 2026-09-02
"""
from alembic import op
from sqlalchemy import text as sa_text

revision = 'merge_tokens_table_001'
down_revision = 'waitlist_email_norm_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_type VARCHAR(32) NOT NULL,
            token_hash VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            use_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tokens_user_id ON tokens (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tokens_token_type ON tokens (token_type)")

    op.execute("""
        INSERT INTO tokens (id, user_id, token_type, token_hash, expires_at, used_at, use_count, created_at)
        SELECT id, user_id, 'password_reset', code_hash, expires_at, used_at, use_count, created_at
        FROM password_reset_codes
        ON CONFLICT (id) DO NOTHING
    """)
    op.execute("""
        INSERT INTO tokens (id, user_id, token_type, token_hash, expires_at, used_at, use_count, created_at)
        SELECT id, user_id, 'email_verification', token_hash, expires_at, used_at, 0, created_at
        FROM email_verification_tokens
        ON CONFLICT (id) DO NOTHING
    """)
    op.execute("""
        INSERT INTO tokens (id, user_id, token_type, token_hash, expires_at, used_at, use_count, created_at)
        SELECT id, user_id, 'account_deletion', token_hash, expires_at, used_at, 0, created_at
        FROM account_deletion_tokens
        ON CONFLICT (id) DO NOTHING
    """)

    # token_hash unique across the merged table — a collision here would mean
    # two independently-generated secrets.token_urlsafe(32) secrets hashed to
    # the same SHA-256 digest, which is not realistically possible.
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_tokens_token_hash ON tokens (token_hash)")

    op.execute("DROP TABLE IF EXISTS password_reset_codes")
    op.execute("DROP TABLE IF EXISTS email_verification_tokens")
    op.execute("DROP TABLE IF EXISTS account_deletion_tokens")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_codes (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            code_hash VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            attempts INTEGER NOT NULL DEFAULT 0,
            use_count INTEGER NOT NULL DEFAULT 0
        )
    """)
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
        CREATE TABLE IF NOT EXISTS account_deletion_tokens (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_email_verification_tokens_user_id ON email_verification_tokens (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_account_deletion_tokens_user_id ON account_deletion_tokens (user_id)")

    op.execute("""
        INSERT INTO password_reset_codes (id, user_id, code_hash, expires_at, used_at, use_count, created_at)
        SELECT id, user_id, token_hash, expires_at, used_at, use_count, created_at
        FROM tokens WHERE token_type = 'password_reset'
    """)
    op.execute("""
        INSERT INTO email_verification_tokens (id, user_id, token_hash, expires_at, used_at, created_at)
        SELECT id, user_id, token_hash, expires_at, used_at, created_at
        FROM tokens WHERE token_type = 'email_verification'
    """)
    op.execute("""
        INSERT INTO account_deletion_tokens (id, user_id, token_hash, expires_at, used_at, created_at)
        SELECT id, user_id, token_hash, expires_at, used_at, created_at
        FROM tokens WHERE token_type = 'account_deletion'
    """)

    op.execute("DROP TABLE IF EXISTS tokens")
