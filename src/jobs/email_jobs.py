"""arq job wrappers for transactional email.

One per src.utils.email sender that a web-request handler needs to fire,
registered in src/worker.py's WorkerSettings.functions. Call sites in
src/routers/auth.py and src/classes/ollama_connector.py enqueue these via
src.queue.enqueue by name instead of using FastAPI BackgroundTasks, so
delivery happens in the dedicated `worker` process rather than stealing
time from the process serving live requests.

send_account_deleted_email is deliberately NOT wrapped here — it's only
ever called from account_deletion_sweep (src/jobs/account_deletion.py),
which already runs inside the worker process, so there's nothing to
enqueue.
"""

from src.utils.email import (
    send_verification_email,
    send_password_reset_email,
    send_delete_account_request_email,
    send_delete_account_scheduled_email,
    send_delete_account_cancelled_email,
    send_fallback_alert,
    send_waitlist_joined_email,
)


async def send_verification_email_job(ctx, *, to, name, token, frontend_url) -> None:
    await send_verification_email(to=to, name=name, token=token, frontend_url=frontend_url)


async def send_password_reset_email_job(ctx, *, to, name, link) -> None:
    await send_password_reset_email(to=to, name=name, link=link)


async def send_delete_account_request_email_job(ctx, *, to, name, link) -> None:
    await send_delete_account_request_email(to=to, name=name, link=link)


async def send_delete_account_scheduled_email_job(ctx, *, to, name, deletion_date) -> None:
    await send_delete_account_scheduled_email(to=to, name=name, deletion_date=deletion_date)


async def send_delete_account_cancelled_email_job(ctx, *, to, name) -> None:
    await send_delete_account_cancelled_email(to=to, name=name)


async def send_fallback_alert_job(ctx, *, model) -> None:
    await send_fallback_alert(model)


async def send_waitlist_joined_email_job(ctx, *, to, name) -> None:
    await send_waitlist_joined_email(to=to, name=name)
