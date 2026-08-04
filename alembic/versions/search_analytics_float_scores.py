"""Widen search_analytics score columns to double precision

The three score columns were Integer because calculate_search_metrics assumed
OpenSearch returned 0-1 relevance scores and stored int(score * 100). The
hybrid query's scores were never in that range (~5-20 observed, and now fused
RRF scores of ~0.01-0.03), so the stored values were meaningless and an int
column would truncate every RRF score to 0.

Pre-existing rows are left in place deliberately — they are converted to
float but stay meaningless, and are documented as unusable for tuning rather
than deleted.

Revision ID: search_analytics_float_scores
Revises: split_user_name_001
Create Date: 2026-08-04

Note the identifier deliberately drops the usual _001 suffix: alembic_version
.version_num is varchar(32), and this id with the suffix was 33 characters —
the DDL applied and then the version bookkeeping UPDATE failed, rolling the
whole migration back. Keep new revision ids under 32 characters.
"""
from alembic import op

revision = 'search_analytics_float_scores'
down_revision = 'split_user_name_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER ... TYPE is naturally idempotent: re-running against a column that
    # is already double precision is a no-op, so this follows the same
    # re-runnable-migration rule as the CREATE ... IF NOT EXISTS pattern.
    op.execute("""
        ALTER TABLE search_analytics
            ALTER COLUMN top_score TYPE double precision,
            ALTER COLUMN avg_score TYPE double precision,
            ALTER COLUMN min_score TYPE double precision
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE search_analytics
            ALTER COLUMN top_score TYPE integer USING round(top_score),
            ALTER COLUMN avg_score TYPE integer USING round(avg_score),
            ALTER COLUMN min_score TYPE integer USING round(min_score)
    """)
