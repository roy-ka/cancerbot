"""arq worker entry point.

Runs as its own container (see the `worker` service in docker-compose.yml,
mirroring the existing `url-classifier` service pattern) via:
  arq src.worker.WorkerSettings

Phase 1 (infrastructure only): no jobs registered yet. Later phases move
the account-deletion sweep, auth-cleanup sweep, email delivery, and
url_classifier onto this — each as a job function added to `functions`/
`cron_jobs` below, with `enqueue_job` calls replacing the current
BackgroundTasks / polling-loop call sites.
"""

import logging
import os

from arq.connections import RedisSettings

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
    cron_jobs: list = []
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = get_redis_settings()
