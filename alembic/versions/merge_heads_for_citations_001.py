"""Merge add_model_name_to_messages_001 and c3d4e5f6a7b8 branches

Revision ID: merge_heads_for_citations_001
Revises: add_model_name_to_messages_001, c3d4e5f6a7b8
Create Date: 2026-07-15
"""
from alembic import op

revision = 'merge_heads_for_citations_001'
down_revision = ('add_model_name_to_messages_001', 'c3d4e5f6a7b8')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
