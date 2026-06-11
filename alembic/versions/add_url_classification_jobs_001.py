"""Add url_classification_jobs table

Revision ID: add_url_classification_jobs_001
Revises: add_urls_to_messages_001
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'add_url_classification_jobs_001'
down_revision = 'add_urls_to_messages_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'url_classification_jobs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('content_text', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('cancer_related', sa.Boolean(), nullable=True),
        sa.Column('llm_reasoning', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_url_classification_jobs_status', 'url_classification_jobs', ['status'])
    op.create_index('ix_url_classification_jobs_created_at', 'url_classification_jobs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_url_classification_jobs_created_at', table_name='url_classification_jobs')
    op.drop_index('ix_url_classification_jobs_status', table_name='url_classification_jobs')
    op.drop_table('url_classification_jobs')
