"""Add user_profiles table and conversations.use_profile_context

user_profiles holds optional clinical context (cancer type, stage, ...) used
to tailor prompt framing. Row existence (not any field being populated) is
what signals "onboarding already offered" — see src/db/models.py:UserProfile.

use_profile_context lets a user opt a single conversation out of having
their profile injected into the prompt.

Revision ID: add_user_profiles_001
Revises: add_messages_truncated_001
Create Date: 2026-09-06
"""
from alembic import op

revision = 'add_user_profiles_001'
down_revision = 'add_messages_truncated_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            cancer_type VARCHAR(255),
            stage VARCHAR(255),
            biomarkers TEXT,
            age_band VARCHAR(50),
            treatment_status VARCHAR(50),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute(
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS use_profile_context BOOLEAN NOT NULL DEFAULT TRUE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS use_profile_context")
    op.execute("DROP TABLE IF EXISTS user_profiles")
