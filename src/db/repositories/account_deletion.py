import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from src.db.models import AccountDeletionToken, User

_TOKEN_TTL_HOURS = 24
_GRACE_PERIOD_DAYS = 7


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_deletion_request_token(db, user_id) -> str:
    """Invalidate any existing unused tokens for the user, create a new one, return plain token."""
    db.query(AccountDeletionToken).filter(
        AccountDeletionToken.user_id == user_id,
        AccountDeletionToken.used_at.is_(None),
    ).delete(synchronize_session=False)

    token = secrets.token_urlsafe(32)
    record = AccountDeletionToken(
        user_id=user_id,
        token_hash=_hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=_TOKEN_TTL_HOURS),
    )
    db.add(record)
    db.commit()
    return token


def verify_deletion_token(db, token: str) -> tuple[AccountDeletionToken | None, str]:
    """
    Validate the deletion token. Returns (record, "") on success or (None, error) on failure.
    Does NOT consume the token — call consume_deletion_token after the password is confirmed.
    """
    record = (
        db.query(AccountDeletionToken)
        .filter(
            AccountDeletionToken.token_hash == _hash_token(token),
            AccountDeletionToken.used_at.is_(None),
        )
        .first()
    )

    if not record:
        return None, "Invalid or already used deletion link."

    now = datetime.now(timezone.utc)
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if now > expires_at:
        return None, "Deletion link has expired."

    return record, ""


def consume_deletion_token(db, record: AccountDeletionToken) -> None:
    """Marks the token used but does NOT commit — call schedule_deletion right after
    so both writes land in the same transaction (a token must never be consumed
    without deletion actually being scheduled, or vice versa)."""
    record.used_at = datetime.now(timezone.utc)


def schedule_deletion(db, user: User) -> datetime:
    """Mark the account for deletion after the grace period and commit.
    Commits any pending changes on `db` too (e.g. consume_deletion_token's used_at)
    so token consumption and scheduling are atomic. Returns the scheduled date."""
    deletion_date = datetime.now(timezone.utc) + timedelta(days=_GRACE_PERIOD_DAYS)
    user.deletion_scheduled_at = deletion_date
    db.commit()
    return deletion_date


def cancel_deletion(db, user_id) -> None:
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.deletion_scheduled_at = None
        db.commit()


def get_users_due_for_deletion(db) -> list[User]:
    now = datetime.now(timezone.utc)
    return (
        db.query(User)
        .filter(User.deletion_scheduled_at.isnot(None), User.deletion_scheduled_at <= now)
        .all()
    )
