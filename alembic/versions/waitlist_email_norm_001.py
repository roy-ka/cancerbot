"""Add normalized_email column to waitlist_entries

Revision ID: waitlist_email_norm_001
Revises: add_waitlist_name_001
Create Date: 2026-09-02
"""
from alembic import op
from sqlalchemy import text as sa_text

revision = 'waitlist_email_norm_001'
down_revision = 'add_waitlist_name_001'
branch_labels = None
depends_on = None

# Mirrors src.utils.email_normalize.normalize_email_for_dedup — duplicated
# here (not imported) so this migration's backfill stays correct as written,
# independent of later changes to that module.
_GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}


def _normalize(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email:
        return email
    local, domain = email.rsplit("@", 1)
    local = local.split("+", 1)[0]
    if domain in _GMAIL_DOMAINS:
        local = local.replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def upgrade() -> None:
    op.execute("ALTER TABLE waitlist_entries ADD COLUMN IF NOT EXISTS normalized_email VARCHAR(320)")

    conn = op.get_bind()
    rows = conn.execute(sa_text(
        "SELECT id, email FROM waitlist_entries WHERE normalized_email IS NULL"
    )).fetchall()
    for row in rows:
        conn.execute(
            sa_text("UPDATE waitlist_entries SET normalized_email = :n WHERE id = :id"),
            {"n": _normalize(row.email), "id": row.id},
        )

    op.execute("ALTER TABLE waitlist_entries ALTER COLUMN normalized_email SET NOT NULL")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_waitlist_entries_normalized_email "
        "ON waitlist_entries (normalized_email)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_waitlist_entries_normalized_email")
    op.execute("ALTER TABLE waitlist_entries DROP COLUMN IF EXISTS normalized_email")
