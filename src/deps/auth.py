from uuid import UUID
from fastapi import Depends, HTTPException, status, Cookie, Header
from sqlalchemy.orm import Session
from jose import JWTError
from src.db.repositories.users import get_user_by_id
from src.deps.db import get_db
from src.auth.security import SecurityUtils


def get_token(
    access_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    if access_token:
        return access_token
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

def get_current_user(
    token: str = Depends(get_token),
    db: Session = Depends(get_db),
):
    try:
        payload = SecurityUtils.decode_jwt_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = get_user_by_id(db=db, user_id=UUID(user_id))
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        if payload.get("tv") != user.token_version:
            raise HTTPException(status_code=401, detail="Token has been invalidated")
        if user.deletion_scheduled_at is not None:
            raise HTTPException(status_code=401, detail="Account pending deletion")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")