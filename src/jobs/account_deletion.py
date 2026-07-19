import asyncio
import logging

from src.db.session import SessionLocal
from src.db.repositories.account_deletion import get_users_due_for_deletion
from src.db.repositories.users import delete_user
from src.utils.email import send_account_deleted_email

logger = logging.getLogger(__name__)

_SWEEP_INTERVAL_SECONDS = 3600


async def _sweep_once(db) -> None:
    due = get_users_due_for_deletion(db)
    for user in due:
        to, name, user_id = user.email, user.name or "User", user.id
        try:
            delete_user(db=db, user_id=user_id)
        except Exception:
            logger.exception("[account-deletion] delete failed user_id=%s", user_id)
            db.rollback()
            continue
        try:
            await send_account_deleted_email(to=to, name=name)
        except Exception:
            logger.exception("[account-deletion] farewell email failed user_id=%s", user_id)
        logger.info("[account-deletion] deleted user_id=%s", user_id)


async def run_account_deletion_sweep() -> None:
    """Background loop — deletes accounts whose grace period has elapsed."""
    while True:
        db = SessionLocal()
        try:
            await _sweep_once(db)
        except Exception:
            logger.exception("[account-deletion] sweep iteration failed")
        finally:
            db.close()
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
