"""Single table (Token, src/db/models.py) backing every single-purpose
token flow: password reset, email verification, account deletion, and
waitlist invites.

Each flow gets its own TTL and its own public function names below (unchanged
from when each lived in its own repository file — src/routers/auth.py's call
sites didn't need to change), but they all go through the same generic
create/verify/consume core so the shared behavior (hash the token, never
store it plain; invalidate a user's prior unused tokens of that type before
issuing a new one; check expires_at) lives in one place.

Every consume_*_token function defers its commit to the caller (commit=False
on the underlying _consume_token call) — the caller commits token
consumption together with whatever DB write the confirmation itself makes
(setting user.email_verified, scheduling deletion, changing the password,
swapping the email), so a token is never consumed without its associated
action actually happening in the same transaction.

_consume_token itself is an atomic UPDATE ... WHERE used_at IS NULL, not a
Python-side attribute assignment — see its docstring. Every caller MUST
check its (and every consume_*_token wrapper's) boolean return value and
abort — raise, don't apply the associated change, don't commit — on False,
which means a concurrent request already consumed that exact token first.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from src.db.models import Token, User, WaitlistEntry
from src.utils.email_normalize import normalize_email_for_dedup

TOKEN_TYPE_PASSWORD_RESET = "password_reset"
TOKEN_TYPE_EMAIL_VERIFICATION = "email_verification"
TOKEN_TYPE_ACCOUNT_DELETION = "account_deletion"
TOKEN_TYPE_WAITLIST_INVITE = "waitlist_invite"
TOKEN_TYPE_EMAIL_CHANGE_REQUEST = "email_change_request"
TOKEN_TYPE_EMAIL_CHANGE = "email_change"
TOKEN_TYPE_EMAIL_REVERT = "email_revert"

_PASSWORD_RESET_TTL_MINUTES = 60
_PASSWORD_RESET_MAX_USES = 5
_EMAIL_VERIFICATION_TTL_HOURS = 24
_ACCOUNT_DELETION_TTL_HOURS = 24
_ACCOUNT_DELETION_GRACE_PERIOD_DAYS = 7
_WAITLIST_INVITE_TTL_HOURS = 48
_EMAIL_CHANGE_REQUEST_TTL_HOURS = 24
_EMAIL_CHANGE_TTL_HOURS = 24
_EMAIL_REVERT_TTL_HOURS = 72


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _create_token(db, user_id, token_type: str, ttl: timedelta, *, target_email: str | None = None) -> str:
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
        target_email=target_email,
        expires_at=datetime.now(timezone.utc) + ttl,
    )
    db.add(record)
    db.commit()
    return token


def _verify_token(
    db, token: str, token_type: str, *,
    not_found_msg: str, expired_msg: str,
    max_uses: int | None = None, max_uses_msg: str | None = None,
    for_update: bool = False,
) -> tuple[Token | None, str]:
    """Validate a token of the given type. Returns (record, "") on success or
    (None, error) on failure. Does NOT consume it — callers call
    _consume_token after the associated action succeeds.

    for_update=True locks the matching row (SELECT ... FOR UPDATE) for the
    rest of the transaction — a modest extra narrowing of the race window
    (blocks a concurrent verify from even reading a "still valid" row while
    this transaction is open) for account deletion, the one flow here with
    real side effects. It is NOT what actually prevents two concurrent
    requests from both completing: any intermediate `db.commit()` between
    this call and _consume_token (e.g. login_attempts' reset_failed_attempts
    in the deletion flow) ends the transaction and releases the lock early.
    The real guard is _consume_token's own atomic UPDATE ... WHERE
    used_at IS NULL — every caller must check its return value and abort
    (no side effect, no commit) on False, regardless of whether for_update
    was used here."""
    query = db.query(Token).filter(
        Token.token_hash == _hash_token(token),
        Token.token_type == token_type,
        Token.used_at.is_(None),
    )
    if for_update:
        query = query.with_for_update()
    record = query.first()

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


def _consume_token(db, record: Token, *, track_use_count: bool = False, commit: bool = True) -> bool:
    """Atomically marks the token used — an UPDATE ... WHERE used_at IS NULL,
    not a Python-side attribute assignment, so two concurrent requests for
    the same token can't both observe it as unconsumed and both proceed.
    SQL UPDATE takes a row lock the instant it runs, even without an
    explicit SELECT ... FOR UPDATE: whichever request's UPDATE executes
    first wins outright (rowcount 1); the second blocks until the first's
    transaction ends, then re-evaluates used_at IS NULL against the
    now-committed row and affects 0 rows. This is the actual race-closing
    step regardless of anything (verify, an unrelated intermediate commit
    elsewhere in the request) that happened before it — callers MUST check
    the return value and abort their side effect (raise, don't commit) on
    False, exactly like a failed verify.

    Returns True if this call consumed it, False if another request already
    had (caller should treat that the same as "invalid or already used")."""
    values = {"used_at": datetime.now(timezone.utc)}
    if track_use_count:
        values["use_count"] = Token.use_count + 1
    result = db.execute(
        update(Token).where(Token.id == record.id, Token.used_at.is_(None)).values(**values)
    )
    consumed = result.rowcount == 1
    if consumed:
        # Keep the in-memory object consistent for any caller that reads
        # record.used_at/use_count after this (e.g. logging, response data).
        record.used_at = values["used_at"]
        if track_use_count:
            record.use_count += 1
    if commit:
        db.commit()
    return consumed


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


def consume_reset_token(db, record: Token) -> bool:
    """Increment use_count and mark the token as used. Does NOT commit —
    caller commits together with the password change itself, and must not
    apply that change at all if this returns False (see _consume_token)."""
    return _consume_token(db, record, track_use_count=True, commit=False)


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
    if not _consume_token(db, record, commit=False):
        # Lost the race to a concurrent request for the same token (e.g. a
        # double-fire from the frontend). The router's caller already has a
        # fallback for "not found" that checks whether the account ended up
        # verified anyway — reuse the same not-found message so that path
        # handles this identically instead of surfacing a raw failure.
        return None, "Invalid or already used verification link."
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
        for_update=True,
    )


def consume_deletion_token(db, record: Token) -> bool:
    """Marks the token used but does NOT commit — see module docstring."""
    return _consume_token(db, record, commit=False)


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
# Email change
# ---------------------------------------------------------------------------
# Three chained token types, one per step of the flow (src/routers/auth.py):
#   1. email_change_request — proves control of the CURRENT inbox before the
#      user is even allowed to type in a new address. Carries no
#      target_email (not chosen yet).
#   2. email_change — created once the new address is submitted (with the
#      current password) on the page the step-1 link leads to; carries the
#      new address as target_email. Confirming it is what actually swaps
#      user.email.
#   3. email_revert — created right after email_change is confirmed, so the
#      OLD address (as target_email) can undo the swap within its window.
# All three commit at creation (via _create_token) but do NOT commit on
# consume — callers commit together with whatever DB write the confirmation
# itself makes, same as email verification and account deletion above.

def create_email_change_request_token(db, user_id) -> str:
    return _create_token(db, user_id, TOKEN_TYPE_EMAIL_CHANGE_REQUEST, timedelta(hours=_EMAIL_CHANGE_REQUEST_TTL_HOURS))


def verify_email_change_request_token(db, token: str) -> tuple[Token | None, str]:
    return _verify_token(
        db, token, TOKEN_TYPE_EMAIL_CHANGE_REQUEST,
        not_found_msg="Invalid or already used link.",
        expired_msg="This link has expired. Please request the email change again.",
    )


def consume_email_change_request_token(db, record: Token) -> bool:
    return _consume_token(db, record, commit=False)


def create_email_change_token(db, user_id, new_email: str) -> str:
    return _create_token(
        db, user_id, TOKEN_TYPE_EMAIL_CHANGE, timedelta(hours=_EMAIL_CHANGE_TTL_HOURS),
        target_email=new_email,
    )


def verify_email_change_token(db, token: str) -> tuple[Token | None, str]:
    return _verify_token(
        db, token, TOKEN_TYPE_EMAIL_CHANGE,
        not_found_msg="Invalid or already used confirmation link.",
        expired_msg="This confirmation link has expired. Please request the email change again.",
    )


def consume_email_change_token(db, record: Token) -> bool:
    return _consume_token(db, record, commit=False)


def create_email_revert_token(db, user_id, old_email: str) -> str:
    return _create_token(
        db, user_id, TOKEN_TYPE_EMAIL_REVERT, timedelta(hours=_EMAIL_REVERT_TTL_HOURS),
        target_email=old_email,
    )


def verify_email_revert_token(db, token: str) -> tuple[Token | None, str]:
    return _verify_token(
        db, token, TOKEN_TYPE_EMAIL_REVERT,
        not_found_msg="Invalid or already used revert link.",
        expired_msg="This revert link has expired.",
    )


def consume_email_revert_token(db, record: Token) -> bool:
    return _consume_token(db, record, commit=False)


def find_consumed_target_email(db, token: str, token_type: str):
    """(user_id, target_email) for an already-consumed token of this type,
    regardless of how long ago it was used. Lets a confirm/revert endpoint
    treat a duplicate request for an already-applied token as an idempotent
    success instead of an error — the same problem verify_email's
    find_token_user_id/already_verified fallback solves for plain email
    verification. Needed here too: both confirm-email-change and
    revert-email pages fire their GET from a bare useEffect, which React
    StrictMode double-invokes in dev, sending the single-use token twice —
    one request wins, the other must not surface as a failure. Returns
    (None, None) if the token doesn't exist or was never consumed.

    user_id is returned as the native UUID (not str) — callers pass it
    straight into get_user_by_id, whose column type needs the real object.
    """
    record = (
        db.query(Token)
        .filter(Token.token_hash == _hash_token(token), Token.token_type == token_type)
        .first()
    )
    if not record or record.used_at is None:
        return None, None
    return record.user_id, record.target_email


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
