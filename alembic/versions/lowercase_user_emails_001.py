"""Lowercase stored user emails

Emails are now lowercased at the API boundary and in the users repository,
so lookups are exact matches against lowercase values. Existing rows stored
with mixed case would otherwise become unreachable at login.

Revision ID: lowercase_user_emails_001
Revises: add_conversation_share_token_001
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'lowercase_user_emails_001'
down_revision = 'add_conversation_share_token_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    collisions = conn.execute(sa.text("""
        SELECT lower(email) AS email, count(*) AS n
        FROM users
        GROUP BY lower(email)
        HAVING count(*) > 1
    """)).fetchall()
    if collisions:
        listed = ", ".join(f"{row.email} ({row.n} accounts)" for row in collisions)
        raise RuntimeError(
            "Cannot lowercase users.email: these addresses exist as multiple accounts "
            f"differing only by case — merge or delete the duplicates first: {listed}"
        )

    op.execute("UPDATE users SET email = lower(email) WHERE email <> lower(email)")
    op.execute(
        "UPDATE tokens SET target_email = lower(target_email) "
        "WHERE target_email IS NOT NULL AND target_email <> lower(target_email)"
    )


def downgrade() -> None:
    # The original casing isn't recoverable, and lowercase emails remain valid
    # under the previous code — nothing to undo.
    pass
