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
        return get_user_by_id(db = db, user_id= user_id)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")