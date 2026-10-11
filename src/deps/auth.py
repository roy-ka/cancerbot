from dataclasses import dataclass
from uuid import UUID
from fastapi import Depends, HTTPException, status, Cookie, Header
from sqlalchemy.orm import Session
from jwt import InvalidTokenError
from src.db.repositories.users import get_user_by_id
from src.deps.db import get_db
from src.auth.security import SecurityUtils

# Sentinel "sub" for the ninja principal below — a well-formed UUID that
# never matches a real users.id row, so a ninja JWT presented to a regular
# get_current_user route fails cleanly with 401 "User not found" instead of
# crashing UUID(...) parsing on something that isn't a UUID at all.
NINJA_SUBJECT_ID = "00000000-0000-0000-0000-000000000001"


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
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@dataclass(frozen=True)
class NinjaPrincipal:
    """Stand-in for a User row — the ninja account isn't backed by the
    database at all (see src/routers/auth.py's login branch), so this
    carries only what the /ninja/* routes actually need off `current_user`."""
    id: str = NINJA_SUBJECT_ID


def get_current_ninja_user(token: str = Depends(get_token)) -> NinjaPrincipal:
    """Independent of get_current_user/the DB — decodes the JWT directly and
    checks the is_ninja claim minted at login. No users table lookup, by
    design: the ninja account has no row to look up."""
    try:
        payload = SecurityUtils.decode_jwt_token(token)
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if not payload.get("is_ninja"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return NinjaPrincipal()