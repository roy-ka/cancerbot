"""Repair: add urls column to messages if missing

Revision ID: repair_add_urls_to_messages_001
Revises: add_url_classification_jobs_001
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'repair_add_urls_to_messages_001'
down_revision = 'add_url_classification_jobs_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE messages
        ADD COLUMN IF NOT EXISTS urls JSON
    """)


def downgrade() -> None:
    op.drop_column('messages', 'urls')
