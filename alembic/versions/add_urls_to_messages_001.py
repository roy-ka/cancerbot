"""Add urls column to messages

Revision ID: add_urls_to_messages_001
Revises: add_bug_reports_table_001
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_urls_to_messages_001'
down_revision = 'add_bug_reports_table_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('urls', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'urls')
