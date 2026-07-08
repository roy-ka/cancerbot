"""Add terms_and_conditions table and users.terms_version

Revision ID: add_terms_and_conditions_001
Revises: add_email_verification_001
Create Date: 2026-07-08
"""
import os
from alembic import op

revision = 'add_terms_and_conditions_001'
down_revision = 'add_email_verification_001'
branch_labels = None
depends_on = None

_SEED_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'seeds', 'terms_v1.txt')


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS terms_and_conditions (
            id SERIAL PRIMARY KEY,
            version INTEGER UNIQUE NOT NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_terms_and_conditions_version
        ON terms_and_conditions (version)
    """)
    # Seed version 1 from seeds/terms_v1.txt
    from sqlalchemy import text as sa_text
    with open(_SEED_FILE, encoding='utf-8') as f:
        seed_text = f.read()
    op.get_bind().execute(
        sa_text("INSERT INTO terms_and_conditions (version, text) VALUES (1, :t) ON CONFLICT (version) DO NOTHING"),
        {"t": seed_text},
    )
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_version INTEGER")
    # Mark all existing users as having accepted version 1 so they aren't locked out
    op.execute("UPDATE users SET terms_version = 1 WHERE terms_version IS NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS terms_version")
    op.drop_table('terms_and_conditions')
