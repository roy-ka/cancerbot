"""Strip :cN chunk suffix from messages.sources_ids

Messages stored before this fix contain chunk-level IDs like ["pmid:123:c0"]
instead of the base source IDs ["pmid:123"]. This migration normalises every
existing row by removing the trailing :cN from each element of the JSON array.

Revision ID: fix_sources_ids_strip_chunk_001
Revises: merge_heads_for_citations_001
Create Date: 2026-07-15
"""
from alembic import op

revision = 'fix_sources_ids_strip_chunk_001'
down_revision = 'merge_heads_for_citations_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use exec_driver_sql to bypass SQLAlchemy's bind-parameter substitution,
    # which would misinterpret ':c' in the regex string as a named parameter.
    op.get_bind().exec_driver_sql("""
        UPDATE messages
        SET sources_ids = (
            SELECT jsonb_agg(to_jsonb(regexp_replace(elem #>> '{}', ':c[0-9]+$', '')))
            FROM jsonb_array_elements(sources_ids::jsonb) AS elem
        )
        WHERE sources_ids IS NOT NULL
          AND sources_ids::text LIKE '%%:c%%'
    """)


def downgrade() -> None:
    pass
