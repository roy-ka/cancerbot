"""Merge cleanup_message_columns and add_bug_reports branches

Revision ID: merge_heads_001
Revises: cleanup_message_columns_001, add_bug_reports_table_001
Create Date: 2026-06-10
"""
from alembic import op

revision = 'merge_heads_001'
down_revision = ('cleanup_message_columns_001', 'add_bug_reports_table_001')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
