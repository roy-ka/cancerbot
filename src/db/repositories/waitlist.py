from datetime import datetime, timezone

from src.db.models import WaitlistEntry
from src.utils.email_normalize import normalize_email_for_dedup


def create_waitlist_entry(db, email: str, name: str) -> WaitlistEntry:
  """Idempotent: re-submitting an email already on the waitlist — or a
  dot/plus-tag variation of one already on it — just returns the existing
  row instead of erroring or duplicating it (name is not updated on a
  repeat submission — the first name given wins)."""
  normalized = normalize_email_for_dedup(email)
  existing = db.query(WaitlistEntry).filter(WaitlistEntry.normalized_email == normalized).first()
  if existing:
    return existing
  entry = WaitlistEntry(email=email, normalized_email=normalized, name=name)
  db.add(entry)
  db.commit()
  return entry


def list_waitlist_entries(db, limit: int = 50, offset: int = 0):
  return (
    db.query(WaitlistEntry)
    .order_by(WaitlistEntry.created_at.asc())
    .offset(offset)
    .limit(limit)
    .all()
  )


def count_waitlist_entries(db) -> int:
  return db.query(WaitlistEntry).count()


def get_waitlist_entry_by_id(db, entry_id) -> WaitlistEntry | None:
  return db.query(WaitlistEntry).filter(WaitlistEntry.id == entry_id).first()


def mark_waitlist_entry_invited(db, entry: WaitlistEntry) -> None:
  """Record that an invite was (re)sent. The actual invite token lives in
  the shared tokens table (src/db/repositories/tokens.py); this just
  updates the audit fields shown in the ninja waitlist view."""
  entry.invited = True
  entry.invited_at = datetime.now(timezone.utc)
  db.commit()
