"""arq worker entry point.

Runs as its own container (see the `worker` service in docker-compose.yml)
via:
  arq src.worker.WorkerSettings

Phase 2: the account-deletion and auth-cleanup sweeps are cron jobs here
instead of the `while True: ... await asyncio.sleep(N)` loops that used to
run inside the backend web process itself (src/main.py's lifespan).
Account deletion later moved off the cron entirely — see the note below.

Phase 5: account deletion is a one-shot job deferred to the exact
deletion_scheduled_at moment (src.queue.enqueue's _defer_until, arq's
native "run this later" feature) instead of an hourly cron scan of the
whole users table. /auth/confirm-delete/ enqueues it directly; a startup
reconciliation (reschedule_pending_deletions) re-enqueues anyone still
pending in case Redis lost the job or this is the first boot after the
migration — see src/jobs/account_deletion.py.

Phase 3: transactional email is enqueued on demand (src.queue.enqueue)
from src/routers/auth.py and src/classes/ollama_connector.py instead of
FastAPI BackgroundTasks — see src/jobs/email_jobs.py.

Phase 4: URL classification replaces its own standalone polling service
(formerly `python -m src.workers.url_classifier`, its own docker-compose
container) with classify_url_job, enqueued immediately when
conversation_helper.py inserts a job row, plus a cron safety net that
catches anything stuck or whose insert-time enqueue failed — see
src/jobs/url_classification.py.
"""

import logging
import os

from arq.connections import RedisSettings
from arq.cron import cron

from src.jobs.account_deletion import delete_scheduled_user_job, reschedule_pending_deletions
from src.jobs.auth_cleanup import auth_cleanup_sweep
from src.jobs.email_jobs import (
    send_verification_email_job,
    send_password_reset_email_job,
    send_delete_account_request_email_job,
    send_delete_account_scheduled_email_job,
    send_delete_account_cancelled_email_job,
    send_fallback_alert_job,
    send_email_change_request_email_job,
    send_email_change_verification_email_job,
    send_email_changed_notice_email_job,
)
from src.jobs.url_classification import (
    classify_url_job,
    reap_and_requeue_stale_url_classification_jobs,
)
from src.jobs.admin_digest import daily_admin_digest, weekly_admin_digest

logger = logging.getLogger(__name__)


def get_redis_settings() -> RedisSettings:
    """Single source of truth for parsing REDIS_URL, used by both the worker
    and any caller enqueueing jobs (so they always agree on which Redis)."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return RedisSettings.from_dsn(redis_url)


async def startup(ctx):
    logger.info("[worker] arq worker starting up")
    await reschedule_pending_deletions(ctx)


async def shutdown(ctx):
    logger.info("[worker] arq worker shutting down")


class WorkerSettings:
    functions = [
        send_verification_email_job,
        send_password_reset_email_job,
        send_delete_account_request_email_job,
        send_delete_account_scheduled_email_job,
        send_delete_account_cancelled_email_job,
        send_fallback_alert_job,
        send_email_change_request_email_job,
        send_email_change_verification_email_job,
        send_email_changed_notice_email_job,
        classify_url_job,
        delete_scheduled_user_job,
    ]
    cron_jobs = [
        # Every 6 hours — matches the old sweep's 6*3600s interval.
        cron(auth_cleanup_sweep, hour={0, 6, 12, 18}, minute=0, run_at_startup=True),
        # Every 5 minutes — matches the old worker's REAP_INTERVAL_SECONDS.
        cron(reap_and_requeue_stale_url_classification_jobs, minute=set(range(0, 60, 5))),
        # Admin-only usage/health digests — see src/jobs/admin_digest.py.
        cron(daily_admin_digest, hour=1, minute=0),
        cron(weekly_admin_digest, weekday='sun', hour=2, minute=0),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = get_redis_settings()
