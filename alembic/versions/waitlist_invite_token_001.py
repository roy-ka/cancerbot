"""Extend tokens table to also carry waitlist invite tokens

user_id becomes nullable and a nullable waitlist_entry_id FK is added, since
a waitlist_invite token belongs to a WaitlistEntry (issued before that
person has a User account at all) rather than to a User. A CHECK constraint
enforces exactly one of the two is ever set.

Revision ID: waitlist_invite_token_001
Revises: merge_tokens_table_001
Create Date: 2026-09-02
"""
from alembic import op

revision = 'waitlist_invite_token_001'
down_revision = 'merge_tokens_table_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tokens ALTER COLUMN user_id DROP NOT NULL")
    op.execute("""
        ALTER TABLE tokens ADD COLUMN IF NOT EXISTS waitlist_entry_id UUID
        REFERENCES waitlist_entries(id) ON DELETE CASCADE
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tokens_waitlist_entry_id ON tokens (waitlist_entry_id)")
    op.execute("""
        ALTER TABLE tokens ADD CONSTRAINT ck_tokens_owner_xor CHECK (
            (user_id IS NOT NULL AND waitlist_entry_id IS NULL)
            OR (user_id IS NULL AND waitlist_entry_id IS NOT NULL)
        )
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE tokens DROP CONSTRAINT IF EXISTS ck_tokens_owner_xor")
    op.execute("DROP INDEX IF EXISTS ix_tokens_waitlist_entry_id")
    op.execute("ALTER TABLE tokens DROP COLUMN IF EXISTS waitlist_entry_id")
    op.execute("ALTER TABLE tokens ALTER COLUMN user_id SET NOT NULL")
