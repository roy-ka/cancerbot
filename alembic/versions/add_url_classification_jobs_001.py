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
    op.execute("""
        CREATE TABLE IF NOT EXISTS url_classification_jobs (
            id UUID PRIMARY KEY,
            url TEXT NOT NULL,
            content_text TEXT NOT NULL,
            title TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            cancer_related BOOLEAN,
            llm_reasoning TEXT,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            processed_at TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_url_classification_jobs_status
        ON url_classification_jobs (status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_url_classification_jobs_created_at
        ON url_classification_jobs (created_at)
    """)


def downgrade() -> None:
    op.drop_index('ix_url_classification_jobs_created_at', table_name='url_classification_jobs')
    op.drop_index('ix_url_classification_jobs_status', table_name='url_classification_jobs')
    op.drop_table('url_classification_jobs')
