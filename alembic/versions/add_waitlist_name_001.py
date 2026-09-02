"""Add name column to waitlist_entries

Revision ID: add_waitlist_name_001
Revises: add_waitlist_table_001
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_waitlist_name_001'
down_revision = 'add_waitlist_table_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE waitlist_entries ADD COLUMN IF NOT EXISTS name VARCHAR(150)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE waitlist_entries DROP COLUMN IF EXISTS name
    """)
