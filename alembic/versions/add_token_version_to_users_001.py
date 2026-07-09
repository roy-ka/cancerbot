"""Add token_version to users for JWT revocation

Revision ID: add_token_version_to_users_001
Revises: add_password_reset_use_count_001
Create Date: 2026-07-09
"""
from alembic import op

revision = 'add_token_version_to_users_001'
down_revision = 'add_password_reset_use_count_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 1
    """)


def downgrade() -> None:
    op.drop_column('users', 'token_version')
