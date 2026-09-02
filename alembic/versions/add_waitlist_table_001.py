"""Add waitlist_entries table

Revision ID: add_waitlist_table_001
Revises: add_terms_v2_001
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_waitlist_table_001'
down_revision = 'add_terms_v2_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS waitlist_entries (
            id UUID PRIMARY KEY,
            email VARCHAR(320) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            invited BOOLEAN NOT NULL DEFAULT FALSE,
            invited_at TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_waitlist_entries_email ON waitlist_entries (email)
    """)


def downgrade() -> None:
    op.drop_table('waitlist_entries')
