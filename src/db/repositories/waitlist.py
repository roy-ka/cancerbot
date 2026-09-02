from src.db.models import WaitlistEntry


def create_waitlist_entry(db, email: str) -> WaitlistEntry:
  """Idempotent: re-submitting an email already on the waitlist just
  returns the existing row instead of erroring or duplicating it."""
  existing = db.query(WaitlistEntry).filter(WaitlistEntry.email == email).first()
  if existing:
    return existing
  entry = WaitlistEntry(email=email)
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
