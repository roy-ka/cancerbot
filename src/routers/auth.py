import os
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, HTTPException, status
from sqlalchemy.orm import Session
from src.deps.db import get_db
from src.auth.security import SecurityUtils
from src.deps.auth import get_current_user, NINJA_SUBJECT_ID
from pydantic import BaseModel, EmailStr, Field
from datetime import timedelta, datetime, timezone
import re
import logging
from src.utils.utils import is_prod
from src.db.repositories.users import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    update_last_login,
    count_all_users,
    email_variation_is_registered,
)
from src.db.repositories.waitlist import create_waitlist_entry
from src.utils.email_normalize import normalize_email_for_dedup
from src.db.repositories.tokens import (
    create_reset_token,
    verify_reset_token,
    consume_reset_token,
    create_verification_token,
    verify_and_consume_token,
    find_token_user_id,
    create_deletion_request_token,
    verify_deletion_token,
    consume_deletion_token,
    schedule_deletion,
    cancel_deletion,
    verify_waitlist_invite_token,
    get_waitlist_invite_entry,
    create_email_change_request_token,
    verify_email_change_request_token,
    consume_email_change_request_token,
    create_email_change_token,
    verify_email_change_token,
    consume_email_change_token,
    create_email_revert_token,
    verify_email_revert_token,
    consume_email_revert_token,
    find_consumed_target_email,
    TOKEN_TYPE_EMAIL_CHANGE,
    TOKEN_TYPE_EMAIL_REVERT,
)
from src.db.repositories.login_attempts import (
    increment_failed_attempts,
    reset_failed_attempts,
    is_account_locked,
    get_remaining_attempts,
)
from src.db.repositories.rate_limit import (
    is_rate_limited,
    record_attempt,
    MAX_REGISTER_ATTEMPTS,
    MAX_FORGOT_PASSWORD_ATTEMPTS,
    MAX_REQUEST_DELETE_ATTEMPTS,
    MAX_WAITLIST_ATTEMPTS,
    MAX_EMAIL_CHANGE_ATTEMPTS,
    MAX_RESEND_VERIFICATION_ATTEMPTS,
)
from src.queue import enqueue
from src.jobs.account_deletion import job_id_for_user

def _get_frontend_url() -> str:
    """Single source of truth for the frontend origin used in email links.

    Falls back to the production domain, not localhost — a missing
    FRONTEND_URL in production must not silently produce localhost links.
    """
    return os.getenv("FRONTEND_URL", "https://cancer-bot.com")


def _get_max_users() -> int | None:
    """Registration cap for slow-growth rollout. Unset/blank = no cap.

    Read from env on every call (not cached at import time) so tests can
    monkeypatch it per-test, matching _get_frontend_url's pattern.
    """
    raw = os.getenv("MAX_USERS", "").strip()
    return int(raw) if raw else None


def _registration_open(db: Session) -> bool:
    max_users = _get_max_users()
    if max_users is None:
        return True
    return count_all_users(db) < max_users


PASSWORD_REGEX_PATTERNS = {
    'lowercase': r'[a-z]',
    'uppercase': r'[A-Z]',
    'digit': r'[0-9]',
    'special': r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]',
}



class CreateUserRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=150)
    last_name: str = Field(..., min_length=1, max_length=150)
    email: EmailStr
    password: str
    invite_token: str | None = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    rememberMe: bool = False


class WaitlistRequest(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=150)



def validate_password(password: str) -> str:
    """Validate password strength. Returns error message or empty string if valid."""
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if not re.search(PASSWORD_REGEX_PATTERNS['lowercase'], password):
        return "Password must contain lowercase letters"
    if not re.search(PASSWORD_REGEX_PATTERNS['uppercase'], password):
        return "Password must contain uppercase letters"
    if not re.search(PASSWORD_REGEX_PATTERNS['digit'], password):
        return "Password must contain numbers"
    if not re.search(PASSWORD_REGEX_PATTERNS['special'], password):
        return "Password must contain special characters"
    return ""

_dummy_password_hash: str | None = None


def _get_dummy_hash() -> str:
    """A throwaway hash used to equalise login timing for unknown emails.

    Without it, `not user or not verify_password(...)` short-circuits, so a
    request for an unregistered address skips a 600k-round pbkdf2 verify and
    comes back measurably sooner — enough to enumerate which emails have
    accounts. Built once per process from a random secret; it exists only to
    be compared against and can never match a real password.
    """
    global _dummy_password_hash
    if _dummy_password_hash is None:
        _dummy_password_hash = SecurityUtils.hash_password(secrets.token_urlsafe(32))
    return _dummy_password_hash


def _client_ip(request: Request) -> str:
    """The peer address of the TCP connection.

    X-Forwarded-For is deliberately NOT trusted: the backend serves traffic
    directly, so the header is fully attacker-controlled and honouring it let
    anyone defeat the per-IP registration rate limit just by rotating a fake
    value. If a reverse proxy is ever put in front of this service, the header
    can be re-enabled — but only for requests whose immediate peer is the
    proxy itself, never unconditionally.
    """
    return request.client.host if request.client else "unknown"

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register/", status_code=201)
async def register_user(req: CreateUserRequest, request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    if is_rate_limited(db, f"register:{ip}"):
        raise HTTPException(status_code=429, detail="Too many registration attempts. Please try again later.")
    record_attempt(db, f"register:{ip}", MAX_REGISTER_ATTEMPTS)

    # Check for an existing account before the capacity cap: re-registering an
    # email that's already taken must still return the normal "already
    # registered" 400, not a confusing "we're full" 403 — the cap only
    # matters for accounts that would actually consume a new slot.
    existing = get_user_by_email(db=db, email=req.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    if not _registration_open(db):
        # A valid, unexpired invite token for this exact email bypasses the
        # cap — that's the whole point of an individual invite (see
        # src/db/repositories/tokens.py:verify_waitlist_invite_token).
        invited = req.invite_token and verify_waitlist_invite_token(db, req.invite_token, req.email)[0]
        if not invited:
            raise HTTPException(
                status_code=403,
                detail="Registration is currently full. Please join the waitlist and we'll invite you once a spot opens up.",
            )

    password_error = validate_password(req.password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)

    password_hash = SecurityUtils.hash_password(req.password)
    user = create_user(
        db=db,
        first_name=req.first_name.strip(),
        last_name=req.last_name.strip(),
        email=req.email,
        password_hash=password_hash,
    )
    token = create_verification_token(db=db, user_id=user.id)
    frontend_url = _get_frontend_url()
    await enqueue("send_verification_email_job", to=user.email, name=user.display_name, token=token, frontend_url=frontend_url)
    resp: dict = {"message": "Please check your email to verify your account.", "email": user.email}
    if not is_prod():
        resp["verification_token"] = token
    return resp


@router.get("/registration_status/")
async def get_registration_status(db: Session = Depends(get_db)):
    """Whether new registrations are currently accepted. No count is
    disclosed publicly — just the open/closed boolean the frontend needs to
    decide whether to show the registration form or the waitlist form."""
    return {"open": _registration_open(db)}


@router.get("/invite_info/")
async def get_invite_info(invite_token: str = Query(...), db: Session = Depends(get_db)):
    """Look up the email/name for a still-valid waitlist invite token, so
    the registration form can pre-fill (and lock) the email field. Does not
    consume the token — /auth/register/ re-validates it at submit time."""
    entry, error = get_waitlist_invite_entry(db, invite_token)
    if not entry:
        raise HTTPException(status_code=400, detail=error)
    return {"email": entry.email, "name": entry.name}


@router.post("/waitlist/", status_code=201)
async def join_waitlist(req: WaitlistRequest, request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    if is_rate_limited(db, f"waitlist:{ip}"):
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
    record_attempt(db, f"waitlist:{ip}", MAX_WAITLIST_ATTEMPTS)

    normalized = normalize_email_for_dedup(req.email)
    if email_variation_is_registered(db, normalized):
        raise HTTPException(status_code=400, detail="You already have an account — log in instead.")

    create_waitlist_entry(db=db, email=req.email, name=req.name.strip())
    await enqueue("send_waitlist_joined_email_job", to=req.email, name=req.name.strip())
    return {"message": "You're on the waitlist! We'll email you an invite once a spot opens up."}


def _ninja_login(req: "LoginRequest", response: Response, db: Session) -> dict | None:
    """The ninja account isn't a users row at all — its credentials live only
    in NINJA_EMAIL/NINJA_PASSWORD. Returns the login response dict on a
    match, or None if this request isn't a ninja login attempt (email
    doesn't match, or the env vars aren't configured) so the caller falls
    through to the normal DB-backed login path."""
    ninja_email = os.getenv("NINJA_EMAIL")
    ninja_password = os.getenv("NINJA_PASSWORD")
    if not ninja_email or not ninja_password or req.email.strip().lower() != ninja_email.strip().lower():
        return None

    # Reuses the existing per-email lockout infra (LoginAttempt is keyed by
    # email string, no FK to a users row needed) so the ninja password can't
    # be brute-forced any more freely than a real account's.
    if is_account_locked(db, ninja_email):
        raise HTTPException(
            status_code=429,
            detail="Account locked due to too many failed login attempts. Please reset your password."
        )

    if not secrets.compare_digest(req.password, ninja_password):
        increment_failed_attempts(db, ninja_email)
        remaining = get_remaining_attempts(db, ninja_email)
        if remaining <= 0:
            raise HTTPException(
                status_code=429,
                detail="Too many failed login attempts. Account locked. Please reset your password."
            )
        raise HTTPException(
            status_code=401,
            detail=f"Invalid email or password. {remaining} attempt(s) remaining before lockout."
        )
    reset_failed_attempts(db, ninja_email)

    # Capped at 2h regardless of rememberMe — a privileged account gets a
    # short session, not the long-lived cookie a real user can opt into.
    expires = datetime.now(timezone.utc) + timedelta(hours=2)
    access_token = SecurityUtils.create_jwt_token({
        "sub": NINJA_SUBJECT_ID, "email": ninja_email, "is_ninja": True, "exp": expires,
    })
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=is_prod(),
        samesite="lax",
        max_age=7200,
        path="/",
    )
    return {"token_type": "bearer", "is_ninja": True}


@router.post("/login/")
async def generate_token(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    ninja_result = _ninja_login(req, response, db)
    if ninja_result is not None:
        return ninja_result

    # Check if account is locked due to too many failed attempts
    if is_account_locked(db, req.email):
        raise HTTPException(
            status_code=429,
            detail="Account locked due to too many failed login attempts. Please reset your password."
        )

    user = get_user_by_email(db=db, email=req.email)
    logging.info(f"Login attempt for email: {req.email}")

    # Always spend the cost of one verify, even when the email is unknown, so
    # response time doesn't disclose whether an account exists.
    if user:
        password_ok = SecurityUtils.verify_password(req.password, user.password_hash)
    else:
        SecurityUtils.verify_password(req.password, _get_dummy_hash())
        password_ok = False

    if not password_ok:
        increment_failed_attempts(db, req.email)
        remaining = get_remaining_attempts(db, req.email)
        if remaining <= 0:
            raise HTTPException(
                status_code=429,
                detail="Too many failed login attempts. Account locked. Please reset your password."
            )
        raise HTTPException(
            status_code=401,
            detail=f"Invalid email or password. {remaining} attempt(s) remaining before lockout."
        )

    if not user.email_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before logging in.")

    reset_failed_attempts(db, req.email)

    if user.deletion_scheduled_at is not None:
        cancel_token = SecurityUtils.create_jwt_token({
            "sub": str(user.id),
            "purpose": "cancel_delete",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        })
        raise HTTPException(
            status_code=403,
            detail={
                "code": "pending_deletion",
                "deletion_date": user.deletion_scheduled_at.isoformat(),
                "cancel_token": cancel_token,
            },
        )

    update_last_login(db=db, user=user)
    if req.rememberMe:
        max_age = 2592000  # 30 days
        expires =  datetime.now(timezone.utc) + timedelta(days=30)
    else:
        max_age = None  # session cookie
        expires =  datetime.now(timezone.utc) + timedelta(hours=1)
    if not is_prod():
        max_age = 31536000 # one year
        expires =  datetime.now(timezone.utc) + timedelta(days=365)

    access_token = SecurityUtils.create_jwt_token({"sub": str(user.id), "email": user.email, "tv": user.token_version, 'exp': expires})
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=is_prod(),
        samesite="lax",
        max_age=max_age,
        path="/",
    )
    return {"token_type": "bearer", "is_ninja": False}

@router.get("/check/")
async def check_auth(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    from src.db.repositories.terms import get_latest_terms
    from src.db.repositories.profile import get_profile
    latest = get_latest_terms(db)
    needs_terms_update = latest is not None and current_user.terms_version != latest.version
    needs_onboarding = get_profile(db, current_user.id) is None
    return {
        "authenticated": True,
        "user_id": str(current_user.id),
        "email": current_user.email,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "terms_version": current_user.terms_version,
        "needs_terms_update": needs_terms_update,
        "needs_onboarding": needs_onboarding,
    }

@router.post("/logout/")
async def logout(response: Response):
    response.delete_cookie(key="access_token", path="/", httponly=True, secure=is_prod(), samesite="lax")
    return {"logged_out": True}


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password/")
async def forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    if is_rate_limited(db, f"forgot-password:{req.email}"):
        raise HTTPException(status_code=429, detail="Too many password reset requests. Please try again later.")
    record_attempt(db, f"forgot-password:{req.email}", MAX_FORGOT_PASSWORD_ATTEMPTS)

    user = get_user_by_email(db=db, email=req.email)
    if user:
        token = create_reset_token(db=db, user_id=user.id)
        frontend_url = _get_frontend_url()
        reset_link = f"{frontend_url}/reset-password?token={token}"
        await enqueue(
            "send_password_reset_email_job",
            to=user.email,
            name=user.display_name,
            link=reset_link,
        )
    return {"ok": True}


@router.post("/reset-password/")
async def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    password_error = validate_password(req.new_password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)

    record, error = verify_reset_token(db=db, token=req.token)
    if not record:
        raise HTTPException(status_code=400, detail=error)

    user = get_user_by_id(db=db, user_id=record.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="User not found.")

    user.password_hash = SecurityUtils.hash_password(req.new_password)
    user.token_version = (user.token_version or 1) + 1
    consume_reset_token(db=db, record=record)
    return {"ok": True}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password/")
async def change_password(
    req: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not SecurityUtils.verify_password(req.current_password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    password_error = validate_password(req.new_password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)

    user = db.merge(current_user)
    user.password_hash = SecurityUtils.hash_password(req.new_password)
    user.token_version = (user.token_version or 1) + 1
    db.commit()
    return {"ok": True}


@router.post("/request-email-change/")
async def request_email_change(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Step 1 of 3 — no new address chosen yet. Proves control of the
    CURRENT inbox (by requiring a click there) before the user is even
    allowed to type in a new one. Throttled per user, same pattern as
    request-delete."""
    change_key = f"email-change:{current_user.id}"
    if is_rate_limited(db, change_key):
        raise HTTPException(status_code=429, detail="Too many email-change requests. Please try again later.")
    record_attempt(db, change_key, MAX_EMAIL_CHANGE_ATTEMPTS)

    token = create_email_change_request_token(db=db, user_id=current_user.id)
    frontend_url = _get_frontend_url()
    link = f"{frontend_url}/change-email?token={token}"
    await enqueue(
        "send_email_change_request_email_job",
        to=current_user.email,
        name=current_user.display_name,
        link=link,
    )
    resp: dict = {"ok": True}
    if not is_prod():
        resp["email_change_request_token"] = token
    return resp


class SubmitNewEmailRequest(BaseModel):
    token: str
    new_email: EmailStr
    password: str


@router.post("/change-email/")
async def submit_new_email(req: SubmitNewEmailRequest, db: Session = Depends(get_db)):
    """Step 2 of 3 — the page the step-1 email links to. Public (token-
    gated, not an authenticated session) since the click may land on a
    different device than the one that requested the change, same as
    confirm-delete. The password re-check happens here rather than at
    step 1, right before the new address is actually chosen."""
    record, error = verify_email_change_request_token(db=db, token=req.token)
    if not record:
        raise HTTPException(status_code=400, detail=error)

    user = get_user_by_id(db=db, user_id=record.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Account not found.")

    if not SecurityUtils.verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    if req.new_email == user.email:
        raise HTTPException(status_code=400, detail="New email must be different from your current one.")

    if get_user_by_email(db=db, email=req.new_email):
        raise HTTPException(status_code=400, detail="Email already registered")

    consume_email_change_request_token(db=db, record=record)
    change_token = create_email_change_token(db=db, user_id=user.id, new_email=req.new_email)
    db.commit()

    frontend_url = _get_frontend_url()
    link = f"{frontend_url}/confirm-email-change?token={change_token}"
    await enqueue(
        "send_email_change_verification_email_job",
        to=req.new_email,
        name=user.display_name,
        old_email=user.email,
        link=link,
    )
    resp: dict = {"ok": True}
    if not is_prod():
        resp["email_change_token"] = change_token
    return resp


@router.get("/confirm-email-change/")
async def confirm_email_change(token: str = Query(...), db: Session = Depends(get_db)):
    """Step 3 of 3 — clicked from the NEW address. This is what actually
    swaps user.email; email_verified is set True since this click is
    itself the proof of ownership. Also starts the revert window by
    emailing the OLD address a time-limited undo link."""
    record, error = verify_email_change_token(db=db, token=token)
    if not record:
        # A duplicate request for a token another request already consumed
        # (e.g. React StrictMode double-firing this page's mount effect in
        # dev) must not surface as a failure when the swap it asked for
        # already happened — same idempotency verify_email's
        # already_verified fallback provides for plain email verification.
        dup_user_id, dup_target_email = find_consumed_target_email(db, token, TOKEN_TYPE_EMAIL_CHANGE)
        if dup_user_id and dup_target_email:
            user = get_user_by_id(db=db, user_id=dup_user_id)
            if user and user.email == dup_target_email:
                return {"ok": True, "message": "Email updated. Please log in with your new email."}
        raise HTTPException(status_code=400, detail=error)

    user = get_user_by_id(db=db, user_id=record.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Account not found.")

    new_email = record.target_email
    if get_user_by_email(db=db, email=new_email):
        # Someone else registered this exact address in the window between
        # step 2 and this click — extremely unlikely, but must not silently
        # steal it or crash on the unique constraint.
        raise HTTPException(status_code=400, detail="That email is no longer available.")

    old_email = user.email
    consume_email_change_token(db=db, record=record)
    user.email = new_email
    user.email_verified = True
    user.token_version = (user.token_version or 1) + 1
    db.commit()

    revert_token = create_email_revert_token(db=db, user_id=user.id, old_email=old_email)
    frontend_url = _get_frontend_url()
    revert_link = f"{frontend_url}/revert-email?token={revert_token}"
    await enqueue(
        "send_email_changed_notice_email_job",
        to=old_email,
        name=user.display_name,
        new_email=new_email,
        link=revert_link,
    )
    resp: dict = {"ok": True, "message": "Email updated. Please log in with your new email."}
    if not is_prod():
        resp["email_revert_token"] = revert_token
    return resp


@router.get("/revert-email/")
async def revert_email(token: str = Query(...), db: Session = Depends(get_db)):
    """Undoes a completed email change, restoring the address the
    email_changed_notice was sent to. email_verified is restored to True
    (the account already reached that state before the change)."""
    record, error = verify_email_revert_token(db=db, token=token)
    if not record:
        # Same duplicate-request idempotency as confirm-email-change above.
        dup_user_id, dup_target_email = find_consumed_target_email(db, token, TOKEN_TYPE_EMAIL_REVERT)
        if dup_user_id and dup_target_email:
            user = get_user_by_id(db=db, user_id=dup_user_id)
            if user and user.email == dup_target_email:
                return {"ok": True, "message": "Your email address has been reverted."}
        raise HTTPException(status_code=400, detail=error)

    user = get_user_by_id(db=db, user_id=record.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Account not found.")

    consume_email_revert_token(db=db, record=record)
    user.email = record.target_email
    user.email_verified = True
    user.token_version = (user.token_version or 1) + 1
    db.commit()
    return {"ok": True, "message": "Your email address has been reverted."}


@router.post("/request-delete/")
async def request_delete_account(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Throttle per user (this endpoint is authenticated) so a hijacked session
    # or buggy client can't spam deletion-confirmation emails at an account.
    delete_key = f"request-delete:{current_user.id}"
    if is_rate_limited(db, delete_key):
        raise HTTPException(status_code=429, detail="Too many account-deletion requests. Please try again later.")
    record_attempt(db, delete_key, MAX_REQUEST_DELETE_ATTEMPTS)

    token = create_deletion_request_token(db=db, user_id=current_user.id)
    frontend_url = _get_frontend_url()
    link = f"{frontend_url}/confirm-delete?token={token}"
    await enqueue(
        "send_delete_account_request_email_job",
        to=current_user.email,
        name=current_user.display_name,
        link=link,
    )
    resp: dict = {"ok": True}
    if not is_prod():
        resp["deletion_token"] = token
    return resp


class ConfirmDeleteRequest(BaseModel):
    token: str
    password: str


@router.post("/confirm-delete/")
async def confirm_delete_account(
    req: ConfirmDeleteRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    record, error = verify_deletion_token(db=db, token=req.token)
    if not record:
        raise HTTPException(status_code=400, detail=error)

    user = get_user_by_id(db=db, user_id=record.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="User not found.")

    if is_account_locked(db, user.email):
        raise HTTPException(
            status_code=429,
            detail="Account locked due to too many failed login attempts. Please reset your password."
        )

    if not SecurityUtils.verify_password(req.password, user.password_hash):
        attempt = increment_failed_attempts(db, user.email)
        if attempt.failed_attempts >= 5:
            raise HTTPException(
                status_code=429,
                detail="Too many failed attempts. Account locked. Please reset your password."
            )
        raise HTTPException(status_code=401, detail="Password is incorrect.")
    reset_failed_attempts(db, user.email)

    consume_deletion_token(db=db, record=record)
    deletion_date = schedule_deletion(db=db, user=user)
    await enqueue(
        "send_delete_account_scheduled_email_job",
        to=user.email,
        name=user.display_name,
        deletion_date=deletion_date.strftime("%B %d, %Y"),
    )
    # Fires the actual deletion at exactly deletion_date rather than an
    # hourly sweep finding it later — see src/jobs/account_deletion.py.
    # job_id_for_user makes this idempotent if confirm-delete is somehow
    # called twice for the same schedule.
    await enqueue(
        "delete_scheduled_user_job",
        user_id=str(user.id),
        _defer_until=deletion_date,
        _job_id=job_id_for_user(user.id),
    )
    response.delete_cookie(key="access_token", path="/", httponly=True, secure=is_prod(), samesite="lax")
    return {"ok": True, "deletion_date": deletion_date.isoformat()}


class CancelDeleteRequest(BaseModel):
    cancel_token: str


@router.post("/cancel-delete/")
async def cancel_delete_account(req: CancelDeleteRequest, db: Session = Depends(get_db)):
    try:
        payload = SecurityUtils.decode_jwt_token(req.cancel_token)
    except HTTPException:
        raise HTTPException(status_code=400, detail="Invalid or expired cancellation link.")
    if payload.get("purpose") != "cancel_delete":
        raise HTTPException(status_code=400, detail="Invalid cancellation token.")

    user_id = UUID(payload.get("sub"))
    cancel_deletion(db=db, user_id=user_id)

    user = get_user_by_id(db=db, user_id=user_id)
    if user:
        await enqueue("send_delete_account_cancelled_email_job", to=user.email, name=user.display_name)

    return {"ok": True}


@router.get("/verify-email/")
async def verify_email(token: str = Query(...), db: Session = Depends(get_db)):
    user_id, error = verify_and_consume_token(db=db, token=token)
    if not user_id:
        # Check if the token was already consumed and the user is already verified
        existing_user_id = find_token_user_id(db=db, token=token)
        if existing_user_id:
            user = get_user_by_id(db=db, user_id=existing_user_id)
            if user and user.email_verified:
                return {"ok": True, "already_verified": True, "message": "Your email is already verified."}
        raise HTTPException(status_code=400, detail=error)

    user = get_user_by_id(db=db, user_id=user_id)
    if not user:
        raise HTTPException(status_code=400, detail="User not found.")

    user.email_verified = True
    db.commit()
    return {"ok": True, "already_verified": False, "message": "Email verified. You can now log in."}


class ResendVerificationRequest(BaseModel):
    email: EmailStr


@router.post("/resend-verification/")
async def resend_verification(req: ResendVerificationRequest, db: Session = Depends(get_db)):
    if is_rate_limited(db, f"resend-verification:{req.email}"):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
    record_attempt(db, f"resend-verification:{req.email}", MAX_RESEND_VERIFICATION_ATTEMPTS)

    user = get_user_by_email(db=db, email=req.email)
    resp: dict = {"ok": True}
    if user and not user.email_verified:
        token = create_verification_token(db=db, user_id=user.id)
        frontend_url = _get_frontend_url()
        await enqueue("send_verification_email_job", to=user.email, name=user.display_name, token=token, frontend_url=frontend_url)
        if not is_prod():
            # Same non-prod escape hatch /register/ and /request-delete/ already
            # have. Without it this was the only token-issuing endpoint with no
            # way to obtain the token in dev: only its SHA-256 hash is stored,
            # so a token not captured here is gone for good.
            resp["verification_token"] = token
    # The response shape must not otherwise reveal whether the email exists or
    # is already verified, so `ok` stays unconditional.
    return resp
