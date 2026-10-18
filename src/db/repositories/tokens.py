"""Single table (Token, src/db/models.py) backing every single-purpose
token flow: emailed login codes, account deletion, and email change/revert.

Each flow gets its own TTL and its own public function names below (unchanged
from when each lived in its own repository file — src/routers/auth.py's call
sites didn't need to change), but they all go through the same generic
create/verify/consume core so the shared behavior (hash the token, never
store it plain; invalidate a user's prior unused tokens of that type before
issuing a new one; check expires_at) lives in one place.

Every consume_*_token function defers its commit to the caller (commit=False
on the underlying _consume_token call) — the caller commits token
consumption together with whatever DB write the confirmation itself makes
(setting user.email_verified, scheduling deletion, swapping the email), so a token is never consumed without its associated
action actually happening in the same transaction.

_consume_token itself is an atomic UPDATE ... WHERE used_at IS NULL, not a
Python-side attribute assignment — see its docstring. Every caller MUST
check its (and every consume_*_token wrapper's) boolean return value and
abort — raise, don't apply the associated change, don't commit — on False,
which means a concurrent request already consumed that exact token first.
"""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from src.db.models import Token, User

TOKEN_TYPE_LOGIN_CODE = "login_code"
TOKEN_TYPE_ACCOUNT_DELETION = "account_deletion"
TOKEN_TYPE_EMAIL_CHANGE_REQUEST = "email_change_request"
TOKEN_TYPE_EMAIL_CHANGE = "email_change"
TOKEN_TYPE_EMAIL_REVERT = "email_revert"

LOGIN_CODE_TTL_MINUTES = 10
LOGIN_CODE_MAX_ATTEMPTS = 5
_ACCOUNT_DELETION_TTL_HOURS = 24
_ACCOUNT_DELETION_GRACE_PERIOD_DAYS = 7
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
    this call and _consume_token ends the transaction and releases the lock early.
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

    return record, ""


def _consume_token(db, record: Token, *, commit: bool = True) -> bool:
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
    used_at = datetime.now(timezone.utc)
    result = db.execute(
        update(Token).where(Token.id == record.id, Token.used_at.is_(None)).values(used_at=used_at)
    )
    consumed = result.rowcount == 1
    if consumed:
        # Keep the in-memory object consistent for any caller that reads
        # record.used_at after this (e.g. logging, response data).
        record.used_at = used_at
    if commit:
        db.commit()
    return consumed


# ---------------------------------------------------------------------------
# Login codes
# ---------------------------------------------------------------------------
# The only way to sign in or finish registering: a 6-digit code emailed to
# the address. Keyed by target_email rather than user_id because the ninja
# account (src/routers/auth.py) has no users row — its codes carry
# user_id=None.
#
# Six digits is a million possibilities, so two limits keep guessing
# hopeless: each code dies after LOGIN_CODE_MAX_ATTEMPTS tries, and the
# router caps how many codes an address can be sent per hour.

def _hash_login_code(email: str, code: str) -> str:
    """HMAC keyed with JWT_SECRET, not the plain SHA-256 _hash_token uses.
    A 32-byte random token can't be brute-forced from its hash, but a
    6-digit code can — a million SHA-256s is a few milliseconds — so a
    leaked tokens table would otherwise hand over every live code. The email
    is part of the message so two addresses holding the same code don't
    collide on the unique token_hash column."""
    key = os.environ["JWT_SECRET"].encode()
    return hmac.new(key, f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def create_login_code(db, email: str, user_id=None) -> str:
    """Replace any unused code for this address with a fresh one and return
    it (only its HMAC is stored)."""
    db.query(Token).filter(
        Token.token_type == TOKEN_TYPE_LOGIN_CODE,
        Token.target_email == email,
        Token.used_at.is_(None),
    ).delete(synchronize_session=False)

    code = f"{secrets.randbelow(10**6):06d}"
    db.add(Token(
        user_id=user_id,
        token_type=TOKEN_TYPE_LOGIN_CODE,
        token_hash=_hash_login_code(email, code),
        target_email=email,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=LOGIN_CODE_TTL_MINUTES),
    ))
    db.commit()
    return code


def verify_login_code(db, email: str, code: str) -> tuple[Token | None, str]:
    """Check and consume the address's current code. Returns (record, "")
    on success — consumed but NOT committed, so the caller commits it
    together with the login's own writes — or (None, error).

    Every attempt is counted *before* the comparison, by an atomic
    UPDATE ... WHERE use_count < max. Checking the count first and
    incrementing after a mismatch would let a burst of parallel guesses all
    read the same count and all get a try."""
    not_found = "Invalid or expired code. Please request a new one."
    record = db.query(Token).filter(
        Token.token_type == TOKEN_TYPE_LOGIN_CODE,
        Token.target_email == email,
        Token.used_at.is_(None),
    ).first()
    if not record:
        return None, not_found

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        return None, "This code has expired. Please request a new one."

    counted = db.execute(
        update(Token)
        .where(
            Token.id == record.id,
            Token.used_at.is_(None),
            Token.use_count < LOGIN_CODE_MAX_ATTEMPTS,
        )
        .values(use_count=Token.use_count + 1)
    )
    db.commit()
    if counted.rowcount != 1:
        return None, "Too many incorrect attempts. Please request a new code."
    db.refresh(record)

    if not hmac.compare_digest(record.token_hash, _hash_login_code(email, code)):
        remaining = LOGIN_CODE_MAX_ATTEMPTS - record.use_count
        if remaining <= 0:
            return None, "Too many incorrect attempts. Please request a new code."
        return None, f"Incorrect code. {remaining} attempt(s) left."

    if not _consume_token(db, record, commit=False):
        return None, not_found
    return record, ""


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
#   2. email_change — created once the new address is submitted on the
#      page the step-1 link leads to; carries the
#      new address as target_email. Confirming it is what actually swaps
#      user.email.
#   3. email_revert — created right after email_change is confirmed, so the
#      OLD address (as target_email) can undo the swap within its window.
# All three commit at creation (via _create_token) but do NOT commit on
# consume — callers commit together with whatever DB write the confirmation
# itself makes, same as account deletion above.

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
    success instead of an error. Needed because both confirm-email-change and
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
