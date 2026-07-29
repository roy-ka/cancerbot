"""Background loop that prunes stale auth throttling rows.

`login_attempts` and `rate_limit_entries` are both keyed by attacker-supplied
values — any email submitted to /auth/login/ gets a row, and any client IP
hitting /auth/register/ gets one too. That is deliberate (tracking only known
emails would leak which accounts exist), but it means neither table has a
natural upper bound. This sweep drops rows that are old enough to be
meaningless while never touching one that is still enforcing a lock or block.
"""

import asyncio
import logging

from src.db.session import SessionLocal
from src.db.repositories.login_attempts import delete_stale_attempts
from src.db.repositories.rate_limit import delete_stale_entries

logger = logging.getLogger(__name__)

_SWEEP_INTERVAL_SECONDS = 6 * 3600


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


async def run_auth_cleanup_sweep() -> None:
    """Background loop — prunes stale login-attempt and rate-limit rows."""
    while True:
        db = SessionLocal()
        try:
            sweep_once(db)
        except Exception:
            logger.exception("[auth-cleanup] sweep iteration failed")
            db.rollback()
        finally:
            db.close()
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
