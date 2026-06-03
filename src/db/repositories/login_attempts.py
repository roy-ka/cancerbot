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
    logging.info(f"Checking lock status for {email}: {attempt.failed_attempts if attempt else 'no record'} failed attempts")
    if not attempt or not attempt.locked_until:
        return False

    if datetime.now(timezone.utc) > attempt.locked_until:
        attempt.locked_until = None
        attempt.failed_attempts = 0
        db.commit()
        return False

    return True

def get_remaining_attempts(db: Session, email: str) -> int:
    """Get remaining login attempts before lockout."""
    attempt = db.query(LoginAttempt).filter(LoginAttempt.email == email).first()
    if not attempt:
        return MAX_LOGIN_ATTEMPTS
    return max(0, MAX_LOGIN_ATTEMPTS - attempt.failed_attempts)
