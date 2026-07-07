import os

from fastapi import APIRouter, BackgroundTasks, Depends, Response, HTTPException, status
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
from src.db.repositories.password_resets import create_reset_code, verify_and_consume_code
from src.db.repositories.email_verification import create_verification_token, verify_and_consume_token
from src.db.repositories.login_attempts import (
    increment_failed_attempts,
    reset_failed_attempts,
    is_account_locked,
)
from src.utils.email import send_password_reset_email, send_verification_email

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

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register/", status_code=201)
async def register_user(req: CreateUserRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
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
    return {"message": "Please check your email to verify your account.", "email": user.email}


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
        

    access_token = SecurityUtils.create_jwt_token({"sub": str(user.id), "email": user.email, 'exp': expires})
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
async def check_auth(current_user=Depends(get_current_user)):
    return {"authenticated": True, "user_id": str(current_user.id), "email": current_user.email, "name": current_user.name}

@router.post("/logout/")
async def logout(response: Response):
    response.delete_cookie(key="access_token", path="/", httponly=True, secure=is_prod(), samesite="lax")
    return {"logged_out": True}


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str


@router.post("/forgot-password/")
async def forgot_password(req: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    user = get_user_by_email(db=db, email=req.email)
    if user:
        code = create_reset_code(db=db, user_id=user.id)
        background_tasks.add_task(send_password_reset_email, to=user.email, code=code)
    return {"ok": True}


@router.post("/reset-password/")
async def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = get_user_by_email(db=db, email=req.email)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid code or email.")

    ok, error = verify_and_consume_code(db=db, user_id=user.id, code=req.code)
    if not ok:
        raise HTTPException(status_code=400, detail=error)

    password_error = validate_password(req.new_password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)

    user.password_hash = SecurityUtils.hash_password(req.new_password)
    db.commit()
    return {"ok": True}


from fastapi import Query

@router.get("/verify-email/")
async def verify_email(token: str = Query(...), db: Session = Depends(get_db)):
    user_id, error = verify_and_consume_token(db=db, token=token)
    if not user_id:
        raise HTTPException(status_code=400, detail=error)

    user = get_user_by_id(db=db, user_id=user_id)
    if not user:
        raise HTTPException(status_code=400, detail="User not found.")

    user.email_verified = True
    db.commit()
    return {"ok": True, "message": "Email verified. You can now log in."}


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
