"""arq cron job that prunes stale auth throttling rows.

`rate_limit_entries` is keyed by attacker-supplied values — any email
submitted to /auth/request-code/ gets a row, and any client IP hitting
/auth/register/ gets one too. That is deliberate (tracking only known emails
would leak which accounts exist), but it means the table has no natural
upper bound. `login_attempts` was the password-login lockout; nothing writes
it since sign-in moved to emailed codes, and this sweep drains what's left. This sweep drops rows that are old enough to be
meaningless while never touching one that is still enforcing a lock or block.
"""

import logging

from src.db.session import SessionLocal
from src.db.repositories.login_attempts import delete_stale_attempts
from src.db.repositories.rate_limit import delete_stale_entries

logger = logging.getLogger(__name__)


def sweep_once(db) -> tuple[int, int]:
    """Delete expired throttling rows. Returns (login_attempts, rate_limits)."""
    attempts = delete_stale_attempts(db)
    limits = delete_stale_entries(db)
    if attempts or limits:
        logger.info(
            "[auth-cleanup] pruned %d login attempt(s), %d rate limit entr(ies)",
            attempts,
            limits,
        )
    return attempts, limits


async def auth_cleanup_sweep(ctx) -> None:
    """arq cron job — prunes stale login-attempt and rate-limit rows.

    Scheduled every 6 hours in src/worker.py's WorkerSettings.cron_jobs
    (replaces the previous hand-rolled `while True: ... await
    asyncio.sleep(6 * 3600)` loop that ran inside the backend web process
    itself).
    """
    db = SessionLocal()
    try:
        sweep_once(db)
    except Exception:
        logger.exception("[auth-cleanup] sweep iteration failed")
        db.rollback()
    finally:
        db.close()
