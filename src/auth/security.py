from dotenv import load_dotenv
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from jose import jwt, exceptions
from fastapi import HTTPException, status
import os

load_dotenv()

class SecurityUtils:
  JWT_SECRET: str
  JWT_ALGORITHM: str
  ACCESS_TOKEN_EXPIRE_MINUTES: int

  JWT_SECRET = os.getenv("JWT_SECRET")
  JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
  ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
  pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
  
  @classmethod
  def hash_password(cls, password: str) -> str:
    return cls.pwd_context.hash(password)
  
  @classmethod
  def verify_password(cls, plain_password: str, hashed_password: str) -> bool:
    return cls.pwd_context.verify(plain_password, hashed_password)
  
  @classmethod
  def create_jwt_token(cls, data: dict) -> str:
    to_encode = data.copy()
    encoded_jwt = jwt.encode(to_encode, cls.JWT_SECRET, algorithm=cls.JWT_ALGORITHM)
    return encoded_jwt

  @classmethod
  def decode_jwt_token(cls, token: str) -> dict:
    try:
      payload = jwt.decode(token, cls.JWT_SECRET, algorithms=[cls.JWT_ALGORITHM])
      return payload
    except exceptions.ExpiredSignatureError:
      raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
      )
    except exceptions.JWTError:
      raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
      )