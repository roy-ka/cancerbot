"""Merge add_password_reset_use_count_001 and add_terms_and_conditions_001 branches

These two branches were applied independently on the production database.
This no-op merge migration unifies them so subsequent migrations have a
single parent.

Revision ID: merge_use_count_and_terms_001
Revises: add_password_reset_use_count_001, add_terms_and_conditions_001
Create Date: 2026-07-09
"""
from alembic import op

revision = 'merge_use_count_and_terms_001'
down_revision = ('add_password_reset_use_count_001', 'add_terms_and_conditions_001')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
