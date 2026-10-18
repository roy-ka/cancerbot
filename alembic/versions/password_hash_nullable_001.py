"""Make users.password_hash nullable

Login is now by a 6-digit code emailed to the address, so new accounts have
no password. Existing hashes are left in place, unused.

Revision ID: password_hash_nullable_001
Revises: lowercase_user_emails_001
Create Date: 2026-10-18
"""
from alembic import op

revision = 'password_hash_nullable_001'
down_revision = 'lowercase_user_emails_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DROP NOT NULL is a no-op on a column that's already nullable, so this
    # is safe to re-run.
    op.execute("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL")


def downgrade() -> None:
    # Accounts created after the upgrade have no hash; an empty string never
    # verifies against anything, so it restores the constraint without
    # granting a login.
    op.execute("UPDATE users SET password_hash = '' WHERE password_hash IS NULL")
    op.execute("ALTER TABLE users ALTER COLUMN password_hash SET NOT NULL")
