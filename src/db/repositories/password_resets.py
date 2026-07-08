import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from src.db.models import PasswordResetCode

_TOKEN_TTL_MINUTES = 60
_MAX_USES = 5


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_reset_token(db, user_id) -> str:
    """Invalidate any existing unused tokens for the user, create a new one, return plain token."""
    db.query(PasswordResetCode).filter(
        PasswordResetCode.user_id == user_id,
        PasswordResetCode.used_at.is_(None),
    ).delete(synchronize_session=False)

    token = secrets.token_urlsafe(32)
    record = PasswordResetCode(
        user_id=user_id,
        code_hash=_hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=_TOKEN_TTL_MINUTES),
    )
    db.add(record)
    db.commit()
    return token


def verify_reset_token(db, token: str) -> tuple[PasswordResetCode | None, str]:
    """
    Validate the reset token. Returns (record, "") on success or (None, error) on failure.
    Does NOT consume the token — call consume_reset_token after a successful password change.
    """
    record = (
        db.query(PasswordResetCode)
        .filter(
            PasswordResetCode.code_hash == _hash_token(token),
            PasswordResetCode.used_at.is_(None),
        )
        .first()
    )

    if not record:
        return None, "Invalid or already used reset link."

    now = datetime.now(timezone.utc)
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if now > expires_at:
        return None, "Reset link has expired."

    if record.use_count >= _MAX_USES:
        return None, "Reset link has been used too many times. Please request a new one."

    return record, ""


def consume_reset_token(db, record: PasswordResetCode) -> None:
    """Increment use_count and mark the token as used after a successful password change."""
    record.use_count += 1
    record.used_at = datetime.now(timezone.utc)
    db.commit()
