from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from src.db.models import RateLimitEntry

MAX_REGISTER_ATTEMPTS = 10
MAX_FORGOT_PASSWORD_ATTEMPTS = 5
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
