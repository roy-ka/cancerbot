import hashlib
import random
import string
from datetime import datetime, timedelta, timezone

from src.db.models import PasswordResetCode


_CODE_TTL_MINUTES = 15
_MAX_ATTEMPTS = 5


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def generate_code() -> str:
    return "".join(random.choices(string.digits, k=6))


def create_reset_code(db, user_id) -> str:
    """Invalidate any existing unused codes for the user, create a new one, return plain code."""
    # Invalidate previous unused codes so only one is active at a time
    db.query(PasswordResetCode).filter(
        PasswordResetCode.user_id == user_id,
        PasswordResetCode.used_at.is_(None),
    ).delete(synchronize_session=False)

    code = generate_code()
    record = PasswordResetCode(
        user_id=user_id,
        code_hash=_hash_code(code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MINUTES),
    )
    db.add(record)
    db.commit()
    return code


def verify_and_consume_code(db, user_id, code: str) -> tuple[bool, str]:
    """
    Returns (ok, error_message).
    On success marks the code as used and returns (True, "").
    """
    record = (
        db.query(PasswordResetCode)
        .filter(
            PasswordResetCode.user_id == user_id,
            PasswordResetCode.used_at.is_(None),
        )
        .order_by(PasswordResetCode.created_at.desc())
        .first()
    )

    if not record:
        return False, "No active reset code found."

    if datetime.now(timezone.utc) > record.expires_at:
        return False, "Reset code has expired."

    if record.attempts >= _MAX_ATTEMPTS:
        return False, "Too many incorrect attempts. Please request a new code."

    if record.code_hash != _hash_code(code):
        record.attempts += 1
        db.commit()
        remaining = _MAX_ATTEMPTS - record.attempts
        return False, f"Incorrect code. {remaining} attempt(s) remaining."

    record.used_at = datetime.now(timezone.utc)
    db.commit()
    return True, ""
