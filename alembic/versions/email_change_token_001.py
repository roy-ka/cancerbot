"""Extend tokens table to carry a target email for the email-change flow

target_email holds whichever address a token will set on the account once
confirmed — used by both the email_change token (the new address, chosen on
the /change-email form) and the email_revert token (the old address, to
restore). Nullable since every other token type leaves it unset.

Revision ID: email_change_token_001
Revises: add_user_profiles_001
Create Date: 2026-09-07
"""
from alembic import op

revision = 'email_change_token_001'
down_revision = 'add_user_profiles_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tokens ADD COLUMN IF NOT EXISTS target_email VARCHAR(320)")


def downgrade() -> None:
    op.execute("ALTER TABLE tokens DROP COLUMN IF EXISTS target_email")
