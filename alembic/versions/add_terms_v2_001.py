"""Publish Terms and Conditions v2

Revision ID: add_terms_v2_001
Revises: search_analytics_float_scores
Create Date: 2026-08-25
"""
import os
from alembic import op

revision = 'add_terms_v2_001'
down_revision = 'search_analytics_float_scores'
branch_labels = None
depends_on = None

_SEED_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'seeds', 'terms_v2.txt')


def upgrade() -> None:
    # Seed version 2 from seeds/terms_v2.txt. Existing users keep their stored
    # terms_version (1), so get_latest_terms vs. current_user.terms_version
    # mismatches and they're prompted to re-accept — that's the point of a
    # new version, unlike v1's migration which backfilled everyone to avoid
    # locking out users before the terms feature existed at all.
    from sqlalchemy import text as sa_text
    with open(_SEED_FILE, encoding='utf-8') as f:
        seed_text = f.read()
    op.get_bind().execute(
        sa_text("INSERT INTO terms_and_conditions (version, text) VALUES (2, :t) ON CONFLICT (version) DO NOTHING"),
        {"t": seed_text},
    )


def downgrade() -> None:
    op.execute("DELETE FROM terms_and_conditions WHERE version = 2")
