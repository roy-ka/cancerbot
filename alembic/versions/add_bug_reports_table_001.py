"""Add bug_reports table

Revision ID: add_bug_reports_table_001
Revises: populate_extracted_terms_001
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'add_bug_reports_table_001'
down_revision = 'cleanup_message_columns_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'bug_reports',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('how_to_reproduce', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('bug_reports')
