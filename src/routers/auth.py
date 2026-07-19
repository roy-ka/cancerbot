import os
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, HTTPException, status
from sqlalchemy.orm import Session
from src.deps.db import get_db
from src.auth.security import SecurityUtils
from src.deps.auth import get_current_user
from pydantic import BaseModel, EmailStr
from datetime import timedelta, datetime, timezone
import re
import logging
from src.utils.utils import is_prod
from src.db.repositories.users import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    update_last_login,
)
from src.db.repositories.password_resets import create_reset_token, verify_reset_token, consume_reset_token
from src.db.repositories.email_verification import create_verification_token, verify_and_consume_token, find_token_user_id
from src.db.repositories.account_deletion import (
    create_deletion_request_token,
    verify_deletion_token,
    consume_deletion_token,
    schedule_deletion,
    cancel_deletion,
)
from src.db.repositories.login_attempts import (
    increment_failed_attempts,
    reset_failed_attempts,
    is_account_locked,
)
from src.db.repositories.rate_limit import (
    is_rate_limited,
    record_attempt,
    MAX_REGISTER_ATTEMPTS,
    MAX_FORGOT_PASSWORD_ATTEMPTS,
)
from src.utils.email import (
    send_password_reset_email,
    send_verification_email,
    send_delete_account_request_email,
    send_delete_account_scheduled_email,
)

PASSWORD_REGEX_PATTERNS = {
    'lowercase': r'[a-z]',
    'uppercase': r'[A-Z]',
    'digit': r'[0-9]',
    'special': r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]',
}



class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    rememberMe: bool = False



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

def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register/", status_code=201)
async def register_user(req: CreateUserRequest, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    if is_rate_limited(db, f"register:{ip}"):
        raise HTTPException(status_code=429, detail="Too many registration attempts. Please try again later.")
    record_attempt(db, f"register:{ip}", MAX_REGISTER_ATTEMPTS)

    password_error = validate_password(req.password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)

    existing = get_user_by_email(db=db, email=req.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    password_hash = SecurityUtils.hash_password(req.password)
    user = create_user(
        db=db,
        name=req.name,
        email=req.email,
        password_hash=password_hash,
    )
    token = create_verification_token(db=db, user_id=user.id)
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    background_tasks.add_task(send_verification_email, to=user.email, name=user.name, token=token, frontend_url=frontend_url)
    resp: dict = {"message": "Please check your email to verify your account.", "email": user.email}
    if not is_prod():
        resp["verification_token"] = token
    return resp


@router.post("/login/")
async def generate_token(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    # Check if account is locked due to too many failed attempts
    if is_account_locked(db, req.email):
        raise HTTPException(
            status_code=429,
            detail="Account locked due to too many failed login attempts. Please reset your password."
        )

    user = get_user_by_email(db=db, email=req.email)
    logging.info(f"Login attempt for email: {req.email}")

    if not user or not SecurityUtils.verify_password(req.password, user.password_hash):
        attempt = increment_failed_attempts(db, req.email)
        if attempt.failed_attempts >= 5:
            raise HTTPException(
                status_code=429,
                detail="Too many failed login attempts. Account locked. Please reset your password."
            )
        raise HTTPException(status_code=401, detail="Invalid email or password")

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
    return {"token_type": "bearer"}

@router.get("/check/")
async def check_auth(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    from src.db.repositories.terms import get_latest_terms
    latest = get_latest_terms(db)
    needs_terms_update = latest is not None and current_user.terms_version != latest.version
    return {
        "authenticated": True,
        "user_id": str(current_user.id),
        "email": current_user.email,
        "name": current_user.name,
        "terms_version": current_user.terms_version,
        "needs_terms_update": needs_terms_update,
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
async def forgot_password(req: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if is_rate_limited(db, f"forgot-password:{req.email}"):
        raise HTTPException(status_code=429, detail="Too many password reset requests. Please try again later.")
    record_attempt(db, f"forgot-password:{req.email}", MAX_FORGOT_PASSWORD_ATTEMPTS)

    user = get_user_by_email(db=db, email=req.email)
    if user:
        token = create_reset_token(db=db, user_id=user.id)
        frontend_url = os.getenv("FRONTEND_URL", "https://cancer-bot.com")
        reset_link = f"{frontend_url}/reset-password?token={token}"
        background_tasks.add_task(
            send_password_reset_email,
            to=user.email,
            name=user.name or "User",
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


@router.post("/request-delete/")
async def request_delete_account(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    token = create_deletion_request_token(db=db, user_id=current_user.id)
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    link = f"{frontend_url}/confirm-delete?token={token}"
    background_tasks.add_task(
        send_delete_account_request_email,
        to=current_user.email,
        name=current_user.name or "User",
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
    background_tasks: BackgroundTasks,
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
    background_tasks.add_task(
        send_delete_account_scheduled_email,
        to=user.email,
        name=user.name or "User",
        deletion_date=deletion_date.strftime("%B %d, %Y"),
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

    cancel_deletion(db=db, user_id=UUID(payload.get("sub")))
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
async def resend_verification(req: ResendVerificationRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    user = get_user_by_email(db=db, email=req.email)
    if user and not user.email_verified:
        token = create_verification_token(db=db, user_id=user.id)
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        background_tasks.add_task(send_verification_email, to=user.email, name=user.name, token=token, frontend_url=frontend_url)
    return {"ok": True}
