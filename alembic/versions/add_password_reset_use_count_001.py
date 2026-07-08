"""add use_count to password_reset_codes

Revision ID: add_password_reset_use_count_001
Revises: f6a7b8c9d0e1
Create Date: 2026-07-08
"""
from alembic import op

revision = "add_password_reset_use_count_001"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE password_reset_codes
        ADD COLUMN IF NOT EXISTS use_count INTEGER NOT NULL DEFAULT 0
    """)


def downgrade():
    op.execute("ALTER TABLE password_reset_codes DROP COLUMN IF EXISTS use_count")
