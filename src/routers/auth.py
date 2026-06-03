from fastapi import APIRouter, Depends, Response,HTTPException, status
from sqlalchemy.orm import Session
from src.deps.db import get_db
from src.auth.security import SecurityUtils
from src.deps.auth import get_current_user
from pydantic import BaseModel
from datetime import timedelta,datetime,timezone
from src.utils.utils import is_prod
from src.db.repositories.users import (
    create_user,
    get_user_by_email,
    update_last_login,
)
from src.db.repositories.password_resets import create_reset_code, verify_and_consume_code
from src.utils.email import send_password_reset_email
import logging



class CreateUserRequest(BaseModel):
    name: str
    email: str
    password: str
    
class LoginRequest(BaseModel):
    email: str
    password: str
    rememberMe: bool = False



router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register/", status_code=201)
async def register_user(req: CreateUserRequest, db: Session = Depends(get_db)):
    # Validate password length
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    # Check for existing email first to return a clean error
    existing = get_user_by_email(db=db, email=req.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    password_hash = SecurityUtils.hash_password(req.password)
    user = create_user(
        db=db,
        name=req.name,
        email=req.email,
        password_hash=password_hash ,
    )
    return {"message": "User created", "email": user.email, "user_id": str(user.id)}


@router.post("/login/")
async def generate_token(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = get_user_by_email(db=db, email=req.email)
    logging.info(f"Login attempt for user_id: {user.id if user else 'unknown'}")
    if not user:
        raise HTTPException(status_code=401, detail="Wrong email")
    if not SecurityUtils.verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password")
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
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/check/")
async def check_auth(current_user=Depends(get_current_user)):
    return {"authenticated": True, "user_id": str(current_user.id), "email": current_user.email, "name": current_user.name}

@router.post("/logout/")
async def logout(response: Response):
    response.delete_cookie(key="access_token", path="/", httponly=True, secure=is_prod(), samesite="lax")
    return {"logged_out": True}


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str


@router.post("/forgot-password/")
async def forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = get_user_by_email(db=db, email=req.email)
    # Always return 200 to avoid leaking which emails are registered
    if user:
        code = create_reset_code(db=db, user_id=user.id)
        try:
            await send_password_reset_email(to=user.email, code=code)
        except Exception as e:
            logging.warning(f"Failed to send reset email to {user.email}: {e}")
    return {"ok": True}


@router.post("/reset-password/")
async def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = get_user_by_email(db=db, email=req.email)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid code or email.")

    ok, error = verify_and_consume_code(db=db, user_id=user.id, code=req.code)
    if not ok:
        raise HTTPException(status_code=400, detail=error)

    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    user.password_hash = SecurityUtils.hash_password(req.new_password)
    db.commit()
    return {"ok": True}