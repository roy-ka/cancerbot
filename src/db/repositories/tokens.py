"""Single table (Token, src/db/models.py) backing three single-purpose
token flows: password reset, email verification, and account deletion.

Each flow gets its own TTL and its own public function names below (unchanged
from when each lived in its own repository file — src/routers/auth.py's call
sites didn't need to change), but they all go through the same generic
create/verify/consume core so the shared behavior (hash the token, never
store it plain; invalidate a user's prior unused tokens of that type before
issuing a new one; check expires_at) lives in one place.

Commit timing differs by flow and is preserved exactly:
- password reset's consume_reset_token commits itself.
- email verification's verify_and_consume_token does NOT commit — the
  caller (auth.py's /verify-email/) commits together with setting
  user.email_verified, so both land in one transaction.
- account deletion's consume_deletion_token does NOT commit — the caller
  commits together with schedule_deletion's deletion_scheduled_at write,
  so a token is never consumed without deletion actually being scheduled.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from src.db.models import Token, User

TOKEN_TYPE_PASSWORD_RESET = "password_reset"
TOKEN_TYPE_EMAIL_VERIFICATION = "email_verification"
TOKEN_TYPE_ACCOUNT_DELETION = "account_deletion"

_PASSWORD_RESET_TTL_MINUTES = 60
_PASSWORD_RESET_MAX_USES = 5
_EMAIL_VERIFICATION_TTL_HOURS = 24
_ACCOUNT_DELETION_TTL_HOURS = 24
_ACCOUNT_DELETION_GRACE_PERIOD_DAYS = 7


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _create_token(db, user_id, token_type: str, ttl: timedelta) -> str:
    """Invalidate the user's existing unused tokens of this type, create a
    new one, return the plain token (only the hash is ever stored)."""
    db.query(Token).filter(
        Token.user_id == user_id,
        Token.token_type == token_type,
        Token.used_at.is_(None),
    ).delete(synchronize_session=False)

    token = secrets.token_urlsafe(32)
    record = Token(
        user_id=user_id,
        token_type=token_type,
        token_hash=_hash_token(token),
        expires_at=datetime.now(timezone.utc) + ttl,
    )
    db.add(record)
    db.commit()
    return token


def _verify_token(
    db, token: str, token_type: str, *,
    not_found_msg: str, expired_msg: str,
    max_uses: int | None = None, max_uses_msg: str | None = None,
) -> tuple[Token | None, str]:
    """Validate a token of the given type. Returns (record, "") on success or
    (None, error) on failure. Does NOT consume it — callers call
    _consume_token after the associated action succeeds."""
    record = (
        db.query(Token)
        .filter(
            Token.token_hash == _hash_token(token),
            Token.token_type == token_type,
            Token.used_at.is_(None),
        )
        .first()
    )

    if not record:
        return None, not_found_msg

    now = datetime.now(timezone.utc)
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if now > expires_at:
        return None, expired_msg

    if max_uses is not None and record.use_count >= max_uses:
        return None, max_uses_msg

    return record, ""


def _consume_token(db, record: Token, *, track_use_count: bool = False, commit: bool = True) -> None:
    if track_use_count:
        record.use_count += 1
    record.used_at = datetime.now(timezone.utc)
    if commit:
        db.commit()


def _find_token_user_id(db, token: str, token_type: str) -> str | None:
    """Return the user_id for a token of this type regardless of used state."""
    record = (
        db.query(Token)
        .filter(Token.token_hash == _hash_token(token), Token.token_type == token_type)
        .first()
    )
    return str(record.user_id) if record else None


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

def create_reset_token(db, user_id) -> str:
    return _create_token(db, user_id, TOKEN_TYPE_PASSWORD_RESET, timedelta(minutes=_PASSWORD_RESET_TTL_MINUTES))


def verify_reset_token(db, token: str) -> tuple[Token | None, str]:
    return _verify_token(
        db, token, TOKEN_TYPE_PASSWORD_RESET,
        not_found_msg="Invalid or already used reset link.",
        expired_msg="Reset link has expired.",
        max_uses=_PASSWORD_RESET_MAX_USES,
        max_uses_msg="Reset link has been used too many times. Please request a new one.",
    )


def consume_reset_token(db, record: Token) -> None:
    """Increment use_count and mark the token as used after a successful password change."""
    _consume_token(db, record, track_use_count=True, commit=True)


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

def create_verification_token(db, user_id) -> str:
    return _create_token(db, user_id, TOKEN_TYPE_EMAIL_VERIFICATION, timedelta(hours=_EMAIL_VERIFICATION_TTL_HOURS))


def find_token_user_id(db, token: str) -> str | None:
    """Return the user_id for a verification token regardless of used state."""
    return _find_token_user_id(db, token, TOKEN_TYPE_EMAIL_VERIFICATION)


def verify_and_consume_token(db, token: str) -> tuple[str | None, str]:
    """Returns (user_id, error). user_id is None on failure. Does NOT commit
    — see module docstring."""
    record, error = _verify_token(
        db, token, TOKEN_TYPE_EMAIL_VERIFICATION,
        not_found_msg="Invalid or already used verification link.",
        expired_msg="Verification link has expired. Please request a new one.",
    )
    if not record:
        return None, error
    _consume_token(db, record, commit=False)
    return str(record.user_id), ""


# ---------------------------------------------------------------------------
# Account deletion
# ---------------------------------------------------------------------------

def create_deletion_request_token(db, user_id) -> str:
    return _create_token(db, user_id, TOKEN_TYPE_ACCOUNT_DELETION, timedelta(hours=_ACCOUNT_DELETION_TTL_HOURS))


def verify_deletion_token(db, token: str) -> tuple[Token | None, str]:
    return _verify_token(
        db, token, TOKEN_TYPE_ACCOUNT_DELETION,
        not_found_msg="Invalid or already used deletion link.",
        expired_msg="Deletion link has expired.",
    )


def consume_deletion_token(db, record: Token) -> None:
    """Marks the token used but does NOT commit — see module docstring."""
    _consume_token(db, record, commit=False)


def schedule_deletion(db, user: User) -> datetime:
    """Mark the account for deletion after the grace period and commit.
    Commits any pending changes on `db` too (e.g. consume_deletion_token's
    used_at) so token consumption and scheduling are atomic. Returns the
    scheduled date."""
    deletion_date = datetime.now(timezone.utc) + timedelta(days=_ACCOUNT_DELETION_GRACE_PERIOD_DAYS)
    user.deletion_scheduled_at = deletion_date
    db.commit()
    return deletion_date


def cancel_deletion(db, user_id) -> None:
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.deletion_scheduled_at = None
        db.commit()


def get_users_due_for_deletion(db) -> list[User]:
    now = datetime.now(timezone.utc)
    return (
        db.query(User)
        .filter(User.deletion_scheduled_at.isnot(None), User.deletion_scheduled_at <= now)
        .all()
    )
