"""Split users.name into first_name + last_name

Revision ID: split_user_name_001
Revises: add_ninja_and_hidden_message_001
Create Date: 2026-07-26
"""
from alembic import op

revision = 'split_user_name_001'
down_revision = 'add_ninja_and_hidden_message_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name VARCHAR(150)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name VARCHAR(150)")

    # Backfill from the legacy single `name`: everything before the first space
    # is first_name, the remainder is last_name. Only touch rows that still have
    # a name and haven't been backfilled, so the migration is idempotent.
    op.execute("""
        UPDATE users
        SET first_name = split_part(name, ' ', 1),
            last_name = NULLIF(substring(name FROM position(' ' IN name) + 1), name)
        WHERE name IS NOT NULL AND first_name IS NULL
    """)

    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS name")


def downgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS name VARCHAR(150)")
    op.execute("""
        UPDATE users
        SET name = TRIM(BOTH ' ' FROM COALESCE(first_name, '') || ' ' || COALESCE(last_name, ''))
        WHERE name IS NULL
    """)
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_name")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS first_name")
