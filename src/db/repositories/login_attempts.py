from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from src.db.models import LoginAttempt
import logging

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 30

def get_or_create_login_attempt(db: Session, email: str) -> LoginAttempt:
    """Get or create a login attempt record for an email."""
    attempt = db.query(LoginAttempt).filter(LoginAttempt.email == email).first()
    if not attempt:
        attempt = LoginAttempt(email=email, failed_attempts=0)
        db.add(attempt)
        db.commit()
    return attempt

def increment_failed_attempts(db: Session, email: str) -> LoginAttempt:
    """Increment failed login attempts and lock account if max reached."""
    attempt = get_or_create_login_attempt(db, email)
    attempt.failed_attempts += 1
    attempt.last_attempt_at = datetime.now(timezone.utc)

    if attempt.failed_attempts >= MAX_LOGIN_ATTEMPTS:
        attempt.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES)

    db.commit()
    return attempt

def reset_failed_attempts(db: Session, email: str) -> None:
    """Reset failed attempts to 0 after successful login."""
    attempt = get_or_create_login_attempt(db, email)
    attempt.failed_attempts = 0
    attempt.locked_until = None
    attempt.last_attempt_at = datetime.now(timezone.utc)
    db.commit()

def is_account_locked(db: Session, email: str) -> bool:
    """Check if account is locked due to too many failed attempts."""
    attempt = db.query(LoginAttempt).filter(LoginAttempt.email == email).first()
    if not attempt or not attempt.locked_until:
        return False

    locked_until = attempt.locked_until
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)

    if datetime.now(timezone.utc) > locked_until:
        attempt.locked_until = None
        attempt.failed_attempts = 0
        db.commit()
        return False

    return True

STALE_ATTEMPT_DAYS = 7


def delete_stale_attempts(db: Session, older_than_days: int = STALE_ATTEMPT_DAYS) -> int:
    """Remove login-attempt rows that are old and no longer locking anything.

    A row is created for every email a login is attempted with, including
    addresses that have no account — that symmetry is deliberate (it's what
    stops the endpoint disclosing which emails exist), but it also means an
    attacker can grow this table indefinitely by posting random addresses.
    Rows still inside their lockout window are always kept.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    now = datetime.now(timezone.utc)
    deleted = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.last_attempt_at.isnot(None),
            LoginAttempt.last_attempt_at < cutoff,
            (LoginAttempt.locked_until.is_(None)) | (LoginAttempt.locked_until < now),
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def get_remaining_attempts(db: Session, email: str) -> int:
    """Get remaining login attempts before lockout."""
    attempt = db.query(LoginAttempt).filter(LoginAttempt.email == email).first()
    if not attempt:
        return MAX_LOGIN_ATTEMPTS
    return max(0, MAX_LOGIN_ATTEMPTS - attempt.failed_attempts)
