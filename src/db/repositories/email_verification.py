import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from src.db.models import EmailVerificationToken

_TOKEN_TTL_HOURS = 24


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_verification_token(db, user_id) -> str:
    db.query(EmailVerificationToken).filter(
        EmailVerificationToken.user_id == user_id,
        EmailVerificationToken.used_at.is_(None),
    ).delete(synchronize_session=False)

    token = secrets.token_urlsafe(32)
    record = EmailVerificationToken(
        user_id=user_id,
        token_hash=_hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=_TOKEN_TTL_HOURS),
    )
    db.add(record)
    db.commit()
    return token


def verify_and_consume_token(db, token: str) -> tuple[str | None, str]:
    """Returns (user_id, error). user_id is None on failure."""
    token_hash = _hash_token(token)
    record = (
        db.query(EmailVerificationToken)
        .filter(
            EmailVerificationToken.token_hash == token_hash,
            EmailVerificationToken.used_at.is_(None),
        )
        .first()
    )

    if not record:
        return None, "Invalid or already used verification link."

    now = datetime.now(timezone.utc)
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if now > expires_at:
        return None, "Verification link has expired. Please request a new one."

    record.used_at = now
    db.commit()
    return str(record.user_id), ""
