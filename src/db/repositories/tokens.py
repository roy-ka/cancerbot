"""Single table (Token, src/db/models.py) backing every single-purpose
token flow: password reset, email verification, account deletion, and
waitlist invites.

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

from src.db.models import Token, User, WaitlistEntry
from src.utils.email_normalize import normalize_email_for_dedup

TOKEN_TYPE_PASSWORD_RESET = "password_reset"
TOKEN_TYPE_EMAIL_VERIFICATION = "email_verification"
TOKEN_TYPE_ACCOUNT_DELETION = "account_deletion"
TOKEN_TYPE_WAITLIST_INVITE = "waitlist_invite"

_PASSWORD_RESET_TTL_MINUTES = 60
_PASSWORD_RESET_MAX_USES = 5
_EMAIL_VERIFICATION_TTL_HOURS = 24
_ACCOUNT_DELETION_TTL_HOURS = 24
_ACCOUNT_DELETION_GRACE_PERIOD_DAYS = 7
_WAITLIST_INVITE_TTL_HOURS = 48


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
    """Clears the schedule. The deferred delete_scheduled_user_job (see
    src/jobs/account_deletion.py) that was enqueued for this user's
    original deletion_scheduled_at is not touched here — it re-checks this
    same column when it fires and simply no-ops if it's now None, so there
    is nothing to cancel/abort in Redis."""
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.deletion_scheduled_at = None
        db.commit()


def get_users_pending_deletion(db) -> list[User]:
    """Every user with a deletion still scheduled, regardless of whether
    that date has already passed. Used only for the worker startup
    reconciliation (src/jobs/account_deletion.py:reschedule_pending_deletions)
    — the normal path is a one-shot job deferred at the moment deletion is
    confirmed, not a periodic scan of this."""
    return db.query(User).filter(User.deletion_scheduled_at.isnot(None)).all()


# ---------------------------------------------------------------------------
# Waitlist invite
# ---------------------------------------------------------------------------
# A waitlist invite has no User yet to key off of (it's issued *before*
# registration), so it's tied to waitlist_entry_id instead of user_id —
# see the Token model docstring. A valid, unexpired invite token lets
# /auth/register/ bypass the MAX_USERS cap for that one email.

def create_waitlist_invite_token(db, waitlist_entry_id) -> str:
    """Invalidate the entry's existing unused invite token, create a new
    one, return the plain token. Used for both the first invite and any
    resend — a resend simply supersedes whatever link was sent before."""
    db.query(Token).filter(
        Token.waitlist_entry_id == waitlist_entry_id,
        Token.token_type == TOKEN_TYPE_WAITLIST_INVITE,
        Token.used_at.is_(None),
    ).delete(synchronize_session=False)

    token = secrets.token_urlsafe(32)
    record = Token(
        waitlist_entry_id=waitlist_entry_id,
        token_type=TOKEN_TYPE_WAITLIST_INVITE,
        token_hash=_hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=_WAITLIST_INVITE_TTL_HOURS),
    )
    db.add(record)
    db.commit()
    return token


def get_waitlist_invite_entry(db, token: str) -> tuple[WaitlistEntry | None, str]:
    """Look up the WaitlistEntry (email/name) for a still-valid invite token,
    without needing to already know the email — used by the frontend to
    pre-fill the registration form. Returns (entry, "") on success or
    (None, error) on failure. Does not consume the token."""
    record, error = _verify_token(
        db, token, TOKEN_TYPE_WAITLIST_INVITE,
        not_found_msg="Invalid or expired invite link.",
        expired_msg="This invite link has expired. Please rejoin the waitlist.",
    )
    if not record:
        return None, error

    entry = db.query(WaitlistEntry).filter(WaitlistEntry.id == record.waitlist_entry_id).first()
    if not entry:
        return None, "Invalid or expired invite link."
    return entry, ""


def verify_waitlist_invite_token(db, token: str, email: str) -> tuple[Token | None, str]:
    """Validate an invite token AND that it was issued for this email (so
    a forwarded link can't be used to register a different address under
    someone else's invite). Does NOT consume it — registration succeeding
    is itself the terminal state; see create_reset_token-style callers for
    why other flows explicitly consume but this one doesn't need to."""
    record, error = _verify_token(
        db, token, TOKEN_TYPE_WAITLIST_INVITE,
        not_found_msg="Invalid or expired invite link.",
        expired_msg="This invite link has expired. Please rejoin the waitlist.",
    )
    if not record:
        return None, error

    entry = db.query(WaitlistEntry).filter(WaitlistEntry.id == record.waitlist_entry_id).first()
    if not entry or normalize_email_for_dedup(entry.email) != normalize_email_for_dedup(email):
        return None, "This invite link was sent to a different email address."

    return record, ""
