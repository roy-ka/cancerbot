import logging

from src.db.session import SessionLocal
from src.db.repositories.account_deletion import get_users_due_for_deletion
from src.db.repositories.users import delete_user
from src.utils.email import send_account_deleted_email

logger = logging.getLogger(__name__)


async def _sweep_once(db) -> None:
    due = get_users_due_for_deletion(db)
    for user in due:
        to, name, user_id = user.email, user.display_name, user.id
        try:
            delete_user(db=db, user_id=user_id)
        except Exception:
            logger.exception("[account-deletion] delete failed user_id=%s", user_id)
            db.rollback()
            continue
        try:
            # Best-effort: returns False rather than raising on a delivery
            # failure. The except still guards anything unexpected above that.
            if not await send_account_deleted_email(to=to, name=name):
                logger.warning("[account-deletion] farewell email not sent user_id=%s", user_id)
        except Exception:
            logger.exception("[account-deletion] farewell email failed user_id=%s", user_id)
        logger.info("[account-deletion] deleted user_id=%s", user_id)


async def account_deletion_sweep(ctx) -> None:
    """arq cron job — deletes accounts whose grace period has elapsed.

    Scheduled hourly in src/worker.py's WorkerSettings.cron_jobs (replaces
    the previous hand-rolled `while True: ... await asyncio.sleep(3600)`
    loop that ran inside the backend web process itself).
    """
    db = SessionLocal()
    try:
        await _sweep_once(db)
    except Exception:
        logger.exception("[account-deletion] sweep iteration failed")
        db.rollback()
    finally:
        db.close()
