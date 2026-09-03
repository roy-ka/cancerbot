"""Drop users.is_ninja — the ninja account is no longer a users row at all.

Ninja auth now checks NINJA_EMAIL/NINJA_PASSWORD directly against the .env
values with no DB lookup; see src/routers/auth.py and src/deps/auth.py.

Revision ID: drop_users_is_ninja_001
Revises: message_options_001
Create Date: 2026-09-03
"""
from alembic import op

revision = 'drop_users_is_ninja_001'
down_revision = 'message_options_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_ninja")


def downgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_ninja BOOLEAN NOT NULL DEFAULT FALSE")
