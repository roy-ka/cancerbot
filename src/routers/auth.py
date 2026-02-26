from fastapi import APIRouter, Depends, Response,HTTPException, status
from sqlalchemy.orm import Session
from src.deps.db import get_db
from src.auth.security import SecurityUtils
from src.deps.auth import get_current_user
from pydantic import BaseModel
from datetime import timedelta,datetime,timezone
from src.utils.utils import is_prod
from src.db.repositories.users import (
    create_user ,
    get_user_by_email,
)
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

@router.post("/register/")
async def register_user(req: CreateUserRequest, db: Session = Depends(get_db)):
    # Optional: check for existing email first to return a clean error
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
    return {status.HTTP_201_CREATED: "User created", "user_id": str(user.id)}


@router.post("/login/")
async def generate_token(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = get_user_by_email(db=db, email=req.email)
    logging.info(f"Attempting login for user: {user.id if user else 'unknown'} with email: {req.email}")
    if not user or not SecurityUtils.verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
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
        secure=False,          # True in production (HTTPS). False on localhost.
        samesite="lax",        # good default for same-site usage
        max_age=max_age,
        path="/",
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/check/")
async def check_auth(current_user=Depends(get_current_user)):
    return {"authenticated": True, "user_id": str(current_user.id), "email": current_user.email}