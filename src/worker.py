"""arq worker entry point.

Runs as its own container (see the `worker` service in docker-compose.yml,
mirroring the existing `url-classifier` service pattern) via:
  arq src.worker.WorkerSettings

Phase 2: the account-deletion and auth-cleanup sweeps are cron jobs here
instead of the `while True: ... await asyncio.sleep(N)` loops that used to
run inside the backend web process itself (src/main.py's lifespan). Later
phases move email delivery and url_classifier onto this too — each as a job
function added to `functions`/`cron_jobs` below, with `enqueue_job` calls
replacing the current BackgroundTasks / polling-loop call sites.
"""

import logging
import os

from arq.connections import RedisSettings
from arq.cron import cron

from src.jobs.account_deletion import account_deletion_sweep
from src.jobs.auth_cleanup import auth_cleanup_sweep

logger = logging.getLogger(__name__)


def get_redis_settings() -> RedisSettings:
    """Single source of truth for parsing REDIS_URL, used by both the worker
    and any caller enqueueing jobs (so they always agree on which Redis)."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return RedisSettings.from_dsn(redis_url)


async def startup(ctx):
    logger.info("[worker] arq worker starting up")


async def shutdown(ctx):
    logger.info("[worker] arq worker shutting down")


class WorkerSettings:
    functions: list = []
    cron_jobs = [
        # Hourly on the hour — matches the old sweep's 3600s interval.
        # run_at_startup=True matches the old loop's behavior of sweeping
        # immediately on process start, then on its regular interval.
        cron(account_deletion_sweep, hour=None, minute=0, run_at_startup=True),
        # Every 6 hours — matches the old sweep's 6*3600s interval.
        cron(auth_cleanup_sweep, hour={0, 6, 12, 18}, minute=0, run_at_startup=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = get_redis_settings()
