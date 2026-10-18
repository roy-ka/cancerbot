import os
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, HTTPException
from sqlalchemy.orm import Session
from src.deps.db import get_db
from src.auth.security import SecurityUtils
from src.deps.auth import get_current_user, NINJA_SUBJECT_ID
from pydantic import BaseModel, Field
from datetime import timedelta, datetime, timezone
from src.utils.utils import is_prod, dev_email_shortcuts
from src.db.repositories.users import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    update_last_login,
)
from src.utils.email_normalize import LowercaseEmail
from src.db.repositories.tokens import (
    create_login_code,
    verify_login_code,
    LOGIN_CODE_TTL_MINUTES,
    create_deletion_request_token,
    verify_deletion_token,
    consume_deletion_token,
    schedule_deletion,
    cancel_deletion,
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
from src.db.repositories.rate_limit import (
    is_rate_limited,
    record_attempt,
    MAX_REGISTER_ATTEMPTS,
    MAX_LOGIN_CODE_EMAIL_ATTEMPTS,
    MAX_LOGIN_CODE_IP_ATTEMPTS,
    MAX_REQUEST_DELETE_ATTEMPTS,
    MAX_EMAIL_CHANGE_ATTEMPTS,
)
from src.queue import enqueue
from src.jobs.account_deletion import job_id_for_user

def _get_frontend_url() -> str:
    """Single source of truth for the frontend origin used in email links.

    The localhost fallback only ever applies outside production: src/main.py
    refuses to start in production without FRONTEND_URL.
    """
    return os.getenv("FRONTEND_URL", "").strip() or "http://localhost:5173"


class CreateUserRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=150)
    last_name: str = Field(..., min_length=1, max_length=150)
    email: LowercaseEmail


class RequestCodeRequest(BaseModel):
    email: LowercaseEmail


class VerifyCodeRequest(BaseModel):
    email: LowercaseEmail
    code: str = Field(..., pattern=r"^\d{6}$")
    rememberMe: bool = False


def _client_ip(request: Request) -> str:
    """The peer address of the TCP connection.

    X-Forwarded-For is deliberately NOT trusted: the backend serves traffic
    directly, so the header is fully attacker-controlled and honouring it let
    anyone defeat the per-IP rate limits just by rotating a fake value. If a
    reverse proxy is ever put in front of this service, the header can be
    re-enabled — but only for requests whose immediate peer is the proxy
    itself, never unconditionally.
    """
    return request.client.host if request.client else "unknown"

_LOOPBACK_IPS = frozenset({"127.0.0.1", "::1"})


def _rate_limits_apply(ip: str) -> bool:
    """Outside production, requests from this machine itself aren't rate
    limited: a local E2E run registers around ten throwaway accounts and
    signs in repeatedly from localhost, which used up the hourly budgets and
    made the next run fail. Production always applies the limits, loopback
    included."""
    return is_prod() or ip not in _LOOPBACK_IPS


def _ninja_email() -> str | None:
    """The ninja account isn't a users row at all — it exists only while
    NINJA_EMAIL is set, and signs in with a code sent to that address."""
    return os.getenv("NINJA_EMAIL", "").strip().lower() or None


async def _send_login_code(db: Session, email: str, name: str, user_id=None) -> dict:
    """Issue and email a fresh code, returning the response body.

    `dev_code` carries the code itself only under DEV_EMAIL_SHORTCUTS — never
    merely outside production, the way the link-token endpoints below return
    their tokens. A code is a complete login for the account, so handing it
    out on any non-production deployment (staging included) would let anyone
    sign in as anyone there."""
    code = create_login_code(db, email=email, user_id=user_id)
    await enqueue("send_login_code_email_job", to=email, name=name, code=code, minutes=LOGIN_CODE_TTL_MINUTES)
    resp: dict = {"ok": True, "email": email}
    if dev_email_shortcuts():
        resp["dev_code"] = code
    return resp


def _check_code_send_limit(db: Session, email: str) -> None:
    """At most MAX_LOGIN_CODE_EMAIL_ATTEMPTS codes per address per hour,
    counted for unknown addresses too so the limit can't be used to tell
    them apart. Together with LOGIN_CODE_MAX_ATTEMPTS per code, this caps
    guessing at a few dozen tries an hour against a million codes — and stops
    the endpoint being used to flood someone's inbox."""
    key = f"login-code:{email}"
    if is_rate_limited(db, key):
        raise HTTPException(status_code=429, detail="Too many codes requested for this email. Please try again later.")
    record_attempt(db, key, MAX_LOGIN_CODE_EMAIL_ATTEMPTS)


def _set_session_cookie(response: Response, user, remember_me: bool) -> None:
    if remember_me:
        max_age = 2592000  # 30 days
        expires = datetime.now(timezone.utc) + timedelta(days=30)
    else:
        max_age = None  # session cookie
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
    if not is_prod():
        max_age = 31536000  # one year
        expires = datetime.now(timezone.utc) + timedelta(days=365)

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


router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register/", status_code=201)
async def register_user(req: CreateUserRequest, request: Request, db: Session = Depends(get_db)):
    """Creates the account unverified and emails a code; /verify-code/
    finishes it. Re-registering an address that never entered its code just
    updates the name and sends a new one, so an abandoned sign-up can't lock
    the address out."""
    ip = _client_ip(request)
    if _rate_limits_apply(ip):
        if is_rate_limited(db, f"register:{ip}"):
            raise HTTPException(status_code=429, detail="Too many registration attempts. Please try again later.")
        record_attempt(db, f"register:{ip}", MAX_REGISTER_ATTEMPTS)

    if req.email == _ninja_email():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = get_user_by_email(db=db, email=req.email)
    if user and user.email_verified:
        raise HTTPException(status_code=400, detail="Email already registered")

    if _rate_limits_apply(ip):
        _check_code_send_limit(db, req.email)

    if user:
        user.first_name = req.first_name.strip()
        user.last_name = req.last_name.strip()
        db.commit()
    else:
        user = create_user(
            db=db,
            first_name=req.first_name.strip(),
            last_name=req.last_name.strip(),
            email=req.email,
        )
    return await _send_login_code(db, user.email, user.display_name, user_id=user.id)


@router.post("/request-code/")
async def request_code(req: RequestCodeRequest, request: Request, db: Session = Depends(get_db)):
    """Emails a sign-in code. The response is identical whether or not the
    address has an account, so it can't be used to discover who's
    registered."""
    ip = _client_ip(request)
    if _rate_limits_apply(ip):
        ip_key = f"login-code-ip:{ip}"
        if is_rate_limited(db, ip_key):
            raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
        record_attempt(db, ip_key, MAX_LOGIN_CODE_IP_ATTEMPTS)
        _check_code_send_limit(db, req.email)

    if req.email == _ninja_email():
        return await _send_login_code(db, req.email, "Ninja")

    user = get_user_by_email(db=db, email=req.email)
    if user:
        return await _send_login_code(db, user.email, user.display_name, user_id=user.id)
    return {"ok": True, "email": req.email}


@router.post("/verify-code/")
async def verify_code(req: VerifyCodeRequest, response: Response, db: Session = Depends(get_db)):
    record, error = verify_login_code(db, email=req.email, code=req.code)
    if not record:
        raise HTTPException(status_code=401, detail=error)

    if req.email == _ninja_email():
        db.commit()
        # Capped at 2h regardless of rememberMe — a privileged account gets a
        # short session, not the long-lived cookie a real user can opt into.
        expires = datetime.now(timezone.utc) + timedelta(hours=2)
        access_token = SecurityUtils.create_jwt_token({
            "sub": NINJA_SUBJECT_ID, "email": req.email, "is_ninja": True, "exp": expires,
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

    user = get_user_by_id(db=db, user_id=record.user_id) if record.user_id else None
    if not user or user.email != req.email:
        # The code was issued for this address, so a mismatch means the
        # account changed address (or was deleted) after it was sent.
        db.rollback()
        raise HTTPException(status_code=401, detail="Invalid or expired code. Please request a new one.")

    # Entering a code sent to the address is the proof of ownership that
    # the old verification link used to provide.
    user.email_verified = True
    db.commit()

    if user.deletion_scheduled_at is not None:
        cancel_token = SecurityUtils.create_jwt_token({
            "sub": str(user.id),
            "purpose": "cancel_delete",
            "tv": user.token_version,
            "remember": req.rememberMe,
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
    _set_session_cookie(response, user, req.rememberMe)
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
    new_email: LowercaseEmail


@router.post("/change-email/")
async def submit_new_email(req: SubmitNewEmailRequest, db: Session = Depends(get_db)):
    """Step 2 of 3 — the page the step-1 email links to. Public (token-
    gated, not an authenticated session) since the click may land on a
    different device than the one that requested the change, same as
    confirm-delete. The step-1 link arriving in the current inbox is the
    proof of identity; there's no password to re-check."""
    record, error = verify_email_change_request_token(db=db, token=req.token)
    if not record:
        raise HTTPException(status_code=400, detail=error)

    user = get_user_by_id(db=db, user_id=record.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Account not found.")

    if req.new_email == user.email:
        raise HTTPException(status_code=400, detail="New email must be different from your current one.")

    if get_user_by_email(db=db, email=req.new_email) or req.new_email == _ninja_email():
        raise HTTPException(status_code=400, detail="Email already registered")

    if not consume_email_change_request_token(db=db, record=record):
        # Another request already consumed this exact token — same outcome
        # as "already used". Must not also mint a second change_token below.
        raise HTTPException(status_code=400, detail="Invalid or already used link.")
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
    if not consume_email_change_token(db=db, record=record):
        # Another request already consumed this exact token — treat as a
        # duplicate the same way the "not found" branch above does.
        dup_user_id, dup_target_email = find_consumed_target_email(db, token, TOKEN_TYPE_EMAIL_CHANGE)
        if dup_user_id and dup_target_email:
            dup_user = get_user_by_id(db=db, user_id=dup_user_id)
            if dup_user and dup_user.email == dup_target_email:
                return {"ok": True, "message": "Email updated. Please log in with your new email."}
        raise HTTPException(status_code=400, detail="Invalid or already used confirmation link.")
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

    target_email = record.target_email
    if not consume_email_revert_token(db=db, record=record):
        # Another request already consumed this exact token — treat as a
        # duplicate the same way the "not found" branch above does.
        dup_user_id, dup_target_email = find_consumed_target_email(db, token, TOKEN_TYPE_EMAIL_REVERT)
        if dup_user_id and dup_target_email:
            dup_user = get_user_by_id(db=db, user_id=dup_user_id)
            if dup_user and dup_user.email == dup_target_email:
                return {"ok": True, "message": "Your email address has been reverted."}
        raise HTTPException(status_code=400, detail="Invalid or already used revert link.")
    user.email = target_email
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


@router.post("/confirm-delete/")
async def confirm_delete_account(
    req: ConfirmDeleteRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """The link from /request-delete/'s email. Reaching it proves control
    of the account's inbox — the same proof a sign-in code gives — so no
    further credential is asked for."""
    record, error = verify_deletion_token(db=db, token=req.token)
    if not record:
        raise HTTPException(status_code=400, detail=error)

    user = get_user_by_id(db=db, user_id=record.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="User not found.")

    if not consume_deletion_token(db=db, record=record):
        # Another request already consumed this exact token. This atomic
        # check is what actually closes the race, not verify_deletion_token's
        # row lock.
        raise HTTPException(status_code=400, detail="Invalid or already used deletion link.")
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
async def cancel_delete_account(req: CancelDeleteRequest, response: Response, db: Session = Depends(get_db)):
    """Cancels a scheduled deletion and signs the user in. The cancel token
    is only ever issued by /verify-code/ right after a correct code, and the
    code is spent by then — without signing in here, the user would have to
    request a second code just to get into the account they just rescued."""
    try:
        payload = SecurityUtils.decode_jwt_token(req.cancel_token)
    except HTTPException:
        raise HTTPException(status_code=400, detail="Invalid or expired cancellation link.")
    if payload.get("purpose") != "cancel_delete":
        raise HTTPException(status_code=400, detail="Invalid cancellation token.")

    user = get_user_by_id(db=db, user_id=UUID(payload.get("sub")))
    if not user or payload.get("tv") != user.token_version:
        raise HTTPException(status_code=400, detail="Invalid or expired cancellation link.")

    cancel_deletion(db=db, user_id=user.id)
    await enqueue("send_delete_account_cancelled_email_job", to=user.email, name=user.display_name)

    update_last_login(db=db, user=user)
    _set_session_cookie(response, user, bool(payload.get("remember")))
    return {"ok": True}
