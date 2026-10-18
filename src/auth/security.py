from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import HTTPException, status
import os

load_dotenv()

class SecurityUtils:
  JWT_SECRET: str
  JWT_ALGORITHM: str
  ACCESS_TOKEN_EXPIRE_MINUTES: int

  JWT_SECRET = os.getenv("JWT_SECRET")
  if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET environment variable is not set")
  if len(JWT_SECRET) < 32:
    raise RuntimeError("JWT_SECRET must be at least 32 characters")
  JWT_ALGORITHM = "HS256"
  ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

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
    except jwt.InvalidTokenError:
      # Base class of every PyJWT validation failure, expiry included.
      raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
      )