"""Shared arq Redis pool for enqueueing jobs from the web server process.

Jobs themselves run in the separate `worker` container (src/worker.py);
this module only publishes them from wherever a request handler needs to
kick off background work (currently: transactional email — see
src/jobs/email_jobs.py).
"""

import logging

from arq import create_pool
from arq.connections import ArqRedis

from src.worker import get_redis_settings

logger = logging.getLogger(__name__)

_pool: ArqRedis | None = None


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(get_redis_settings())
    return _pool


async def enqueue(job_name: str, **kwargs) -> None:
    """Enqueue a job by name (must match a function registered in
    src.worker.WorkerSettings.functions).

    Never raises. A queue outage must not turn a successful request (e.g.
    registration) into a 500 — the job simply doesn't run until the queue
    is back, matching every send_* helper in src/utils/email.py already
    logging and swallowing delivery failures rather than surfacing them to
    the caller.
    """
    try:
        pool = await get_pool()
        await pool.enqueue_job(job_name, **kwargs)
    except Exception:
        logger.exception("[queue] failed to enqueue job=%s", job_name)
