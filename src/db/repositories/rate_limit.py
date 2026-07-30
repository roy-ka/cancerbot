from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from src.db.models import RateLimitEntry

MAX_REGISTER_ATTEMPTS = 10
MAX_FORGOT_PASSWORD_ATTEMPTS = 5
MAX_REQUEST_DELETE_ATTEMPTS = 5
BLOCK_MINUTES = 60


def is_rate_limited(db: Session, key: str) -> bool:
    entry = db.query(RateLimitEntry).filter(RateLimitEntry.key == key).first()
    if not entry or not entry.blocked_until:
        return False
    now = datetime.now(timezone.utc)
    blocked_until = entry.blocked_until
    if blocked_until.tzinfo is None:
        blocked_until = blocked_until.replace(tzinfo=timezone.utc)
    if now > blocked_until:
        entry.blocked_until = None
        entry.attempts = 0
        db.commit()
        return False
    return True


STALE_ENTRY_DAYS = 7


def delete_stale_entries(db: Session, older_than_days: int = STALE_ENTRY_DAYS) -> int:
    """Remove rate-limit rows that are old and no longer blocking anything.

    Keys are derived from attacker-supplied values (`register:<ip>`,
    `forgot-password:<email>`), so without pruning this table grows without
    bound. Rows still inside their block window are always kept.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    now = datetime.now(timezone.utc)
    deleted = (
        db.query(RateLimitEntry)
        .filter(
            RateLimitEntry.last_attempt_at.isnot(None),
            RateLimitEntry.last_attempt_at < cutoff,
            (RateLimitEntry.blocked_until.is_(None)) | (RateLimitEntry.blocked_until < now),
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def record_attempt(db: Session, key: str, max_attempts: int, block_minutes: int = BLOCK_MINUTES) -> RateLimitEntry:
    entry = db.query(RateLimitEntry).filter(RateLimitEntry.key == key).first()
    if not entry:
        entry = RateLimitEntry(key=key, attempts=0)
        db.add(entry)
    entry.attempts += 1
    entry.last_attempt_at = datetime.now(timezone.utc)
    if entry.attempts >= max_attempts:
        entry.blocked_until = datetime.now(timezone.utc) + timedelta(minutes=block_minutes)
    db.commit()
    return entry
