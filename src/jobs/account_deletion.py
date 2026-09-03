import logging
import uuid
from datetime import datetime, timezone

from src.db.session import SessionLocal
from src.db.repositories.tokens import get_users_pending_deletion
from src.db.repositories.users import delete_user, get_user_by_id
from src.utils.email import send_account_deleted_email

logger = logging.getLogger(__name__)


def job_id_for_user(user_id) -> str:
    """Deterministic per-user job id — makes enqueueing idempotent, so both
    a cancel-then-reschedule and the startup reconciliation below can
    re-enqueue freely without ever double-scheduling the same user."""
    return f"delete-user-{user_id}"


async def delete_scheduled_user_job(ctx, *, user_id: str) -> None:
    """One-shot job deferred (via arq's _defer_until) to run at a user's
    deletion_scheduled_at — enqueued by /auth/confirm-delete/
    (src/routers/auth.py) instead of being picked up by a recurring cron
    sweep. Re-checks deletion_scheduled_at at execution time: if it's been
    cleared (cancelled) or pushed to a later date (cancel-then-reschedule),
    this run just no-ops — the currently-correct job is whichever one was
    deferred for the *current* deletion_scheduled_at value.
    """
    db = SessionLocal()
    try:
        # arq job kwargs must be JSON-serializable, so the caller passes a
        # plain str — the ORM's UUID column needs a real uuid.UUID.
        user = get_user_by_id(db=db, user_id=uuid.UUID(user_id))
        if user is None:
            logger.info("[account-deletion] user_id=%s no longer exists, skipping", user_id)
            return
        if user.deletion_scheduled_at is None:
            logger.info("[account-deletion] user_id=%s deletion was cancelled, skipping", user_id)
            return

        scheduled = user.deletion_scheduled_at
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        if scheduled > datetime.now(timezone.utc):
            logger.info(
                "[account-deletion] user_id=%s rescheduled to %s, skipping stale run",
                user_id, scheduled,
            )
            return

        to, name = user.email, user.display_name
        try:
            delete_user(db=db, user_id=user.id)
        except Exception:
            logger.exception("[account-deletion] delete failed user_id=%s", user_id)
            db.rollback()
            return

        try:
            # Best-effort: returns False rather than raising on a delivery
            # failure. The except still guards anything unexpected above that.
            if not await send_account_deleted_email(to=to, name=name):
                logger.warning("[account-deletion] farewell email not sent user_id=%s", user_id)
        except Exception:
            logger.exception("[account-deletion] farewell email failed user_id=%s", user_id)

        logger.info("[account-deletion] deleted user_id=%s", user_id)
    finally:
        db.close()


async def reschedule_pending_deletions(ctx) -> None:
    """Worker startup safety net — re-enqueues a deferred
    delete_scheduled_user_job for every user still showing a
    deletion_scheduled_at. Covers a deletion scheduled before this job
    existed, and a deferred job Redis somehow lost (e.g. restarted without
    persistence). Idempotent via job_id_for_user, so this is a no-op for
    anyone whose job is already pending — safe to run on every startup
    rather than needing to track what's already been reconciled.
    """
    from src.queue import enqueue  # local import — avoids a circular import
    # with src.worker (which imports this module and is itself imported by
    # src.queue for get_redis_settings).

    db = SessionLocal()
    try:
        pending = get_users_pending_deletion(db)
    finally:
        db.close()

    for user in pending:
        await enqueue(
            "delete_scheduled_user_job",
            user_id=str(user.id),
            _defer_until=user.deletion_scheduled_at,
            _job_id=job_id_for_user(user.id),
        )
    if pending:
        logger.info("[account-deletion] reconciled %d pending deletion(s) on startup", len(pending))
