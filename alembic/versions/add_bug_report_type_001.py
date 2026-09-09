"""Add report_type to bug_reports (bug vs feedback)

Revision ID: add_bug_report_type_001
Revises: email_change_token_001
Create Date: 2026-09-09
"""
from alembic import op

revision = 'add_bug_report_type_001'
down_revision = 'email_change_token_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE bug_reports
        ADD COLUMN IF NOT EXISTS report_type VARCHAR(20) NOT NULL DEFAULT 'bug'
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE bug_reports DROP COLUMN IF EXISTS report_type")
