import asyncio
import logging
import os
import re
from urllib.parse import urlparse

from src.utils.utils import is_prod
from src.utils.email_brevo import _send_brevo
from src.utils.email_templates import render as _render_template

logger = logging.getLogger(__name__)

_TOKEN_QUERY_RE = re.compile(r"(token=)[^&\s]+", re.IGNORECASE)

# Hosts whose links are worthless to anyone who isn't already on the machine.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"})


def _is_local_link(url: str) -> bool:
    """Whether a link points at this machine.

    A token in a `http://localhost:5173/...` link can only be used by someone
    who can already reach that host — and anyone reading the log can. A token in
    a link to a real hostname is a live credential for a shared deployment.
    """
    try:
        host = (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return False
    return host in _LOCAL_HOSTS


def _redact_token(url: str) -> str:
    """Mask the `token` query-param value in a URL before logging.

    These links are only logged in non-prod, but 'non-prod' includes staging —
    where the root-logger Axiom handler would otherwise ship a live, usable
    reset/verification/deletion token to a third-party log store. Redacting
    keeps the flow visible (path + recipient) without emitting the secret.

    Local links are exempt: masking them protected nothing (the reader is
    already on the host) while making dev flows unusable, since the token is
    stored only as a SHA-256 hash and cannot be recovered afterwards.
    """
    if _is_local_link(url):
        return url or ""
    return _TOKEN_QUERY_RE.sub(r"\1***", url or "")


def _redact_payload(template_data: dict) -> dict:
    """Copy of a template payload with non-local `token=` values masked.

    The dev-mode log below prints the whole payload, and payloads carry the
    verification / reset / deletion links — so without this, turning on
    dev-mode logging would re-introduce exactly the leak `_redact_token` exists
    to prevent (non-prod includes staging, where the Axiom handler ships logs
    to a third party). Links to localhost pass through intact, which is what
    makes the dev flow usable at all.
    """
    return {
        k: _redact_token(v) if isinstance(v, str) else v
        for k, v in (template_data or {}).items()
    }


# Dormant — SendGrid is no longer the active provider (see Brevo path in
# email_brevo.py / email_templates.py). Kept only as a reference for these
# template IDs in case SendGrid is ever reinstated; nothing reads this today.
# SENDGRID_EMAIL_TEMPLATES = {
#     "verification": "d-6a6d6095e74549fbb91c18e741cef813",
#     "password_reset": "d-89a37afdde454f699046dda66cfca385",
#     "fallback_alert": "d-18e52d88f49b4b79b4ff292b1074bd75",
#     "account_deleted": "d-feba610add7d4ad091351504f1a14937",
#     "delete_account_request": "d-4db440ef36e547a0a7e16e35500d935c",
#     "delete_account_scheduled": "d-336a3518ba8140cd9b5689f1aab52a94",
# }

_FALLBACK_ALERT_TO = "roykazaz@gmail.com"


def _send_sendgrid(
    to: str,
    template_id: str,
    template_data: dict,
    *,
    disable_subscription_tracking: bool = False,
) -> None:
    # Outside production, never hand anything to SendGrid — just log what would
    # have been sent. Dev/CI has no business delivering real mail, and a stale
    # or absent SENDGRID_API_KEY otherwise turns every local signup into a 401
    # traceback. NOTE: this keys off is_prod(), so a *staging* deploy also stops
    # sending; give staging its own flag here if it ever needs real delivery.
    if not is_prod():
        logger.info(
            "[email] dev mode — not sending. to=%s template=%s data=%s",
            to,
            template_id,
            _redact_payload(template_data),
        )
        return

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, TrackingSettings, SubscriptionTracking
    except ImportError:
        logger.error("SendGrid SDK not installed. Run: pip install sendgrid")
        return

    api_key = os.getenv("SENDGRID_API_KEY")
    if not api_key:
        logger.warning("[email] SendGrid not configured — would have sent to %s (template %s)", to, template_id)
        return

    message = Mail(from_email=("no-reply@cancer-bot.com", "CancerBot"), to_emails=to)
    message.template_id = template_id
    message.dynamic_template_data = template_data

    if disable_subscription_tracking:
        ts = TrackingSettings()
        ts.subscription_tracking = SubscriptionTracking(enable=False)
        message.tracking_settings = ts

    try:
        sg = SendGridAPIClient(api_key)
        sg.send(message)
        logger.info("[email] sent to=%s template=%s", to, template_id)
    except Exception as e:
        # Raises on purpose: this is the low-level call, and _deliver() is what
        # decides that a delivery failure must not escape a background task.
        logger.error("[email] SendGrid error to=%s template=%s: %s", to, template_id, e)
        raise


async def _deliver(
    to: str,
    template_key: str,
    template_data: dict,
    *,
    disable_subscription_tracking: bool = False,
) -> bool:
    """Send in a worker thread, best-effort. Returns whether it was delivered.

    Never raises. Every caller of the public send_* helpers below registers them
    as FastAPI BackgroundTasks, which run *after* the response has been sent — so
    a propagating exception cannot be reported to the client and surfaces only as
    an unhandled ASGI traceback, for a failure `_send_brevo` has already
    logged. A bad API key or a provider outage must not make a successful
    registration look like a crashed request.

    `disable_subscription_tracking` is accepted for call-site compatibility with
    the dormant SendGrid path but unused here: Brevo's transactional /smtp/email
    endpoint doesn't auto-inject an unsubscribe link the way SendGrid's dynamic
    templates could, so there's nothing to disable.
    """
    try:
        subject, html = _render_template(template_key, **template_data)
        await asyncio.to_thread(_send_brevo, to, subject, html)
        return True
    except Exception as exc:
        logger.error("[email] delivery failed to=%s template=%s: %s", to, template_key, exc)
        return False


async def send_fallback_alert(model: str) -> bool:
    """Alert when Groq fails and generation falls back to Gemini.

    Enqueued via src.jobs.email_jobs.send_fallback_alert_job (see
    src/classes/ollama_connector.py's Groq-failure path) rather than
    called inline — it previously spawned its own background thread here
    to avoid blocking the streaming response; now the queue does that job.
    """
    return await _deliver(_FALLBACK_ALERT_TO, "fallback_alert", {"model": model})


def _admin_digest_recipients() -> list[str]:
    raw = os.getenv("ADMIN_DIGEST_EMAILS", "").strip()
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


async def send_daily_admin_digest_email(template_data: dict) -> int:
    """Send the daily admin digest to every address in ADMIN_DIGEST_EMAILS.

    Returns the number of recipients it was actually delivered to (0 if the
    env var is unset — a deliberate no-op, not an error; see
    src/jobs/admin_digest.py)."""
    delivered = 0
    for to in _admin_digest_recipients():
        if await _deliver(to, "daily_admin_digest", template_data):
            delivered += 1
    return delivered


async def send_weekly_admin_digest_email(template_data: dict) -> int:
    """Same contract as send_daily_admin_digest_email, for the weekly digest."""
    delivered = 0
    for to in _admin_digest_recipients():
        if await _deliver(to, "weekly_admin_digest", template_data):
            delivered += 1
    return delivered


async def send_verification_email(to: str, name: str, token: str, frontend_url: str) -> bool:
    verify_url = f"{frontend_url}/verify-email?token={token}"
    if not is_prod():
        logger.info("[email] verification link for %s: %s", to, _redact_token(verify_url))
    return await _deliver(to, "verification", {"name": name, "link": verify_url})


async def send_account_deleted_email(to: str, name: str) -> bool:
    return await _deliver(
        to,
        "account_deleted",
        {"name": name, "link": "https://cancer-bot.com/signup"},
        disable_subscription_tracking=True,
    )


async def send_password_reset_email(to: str, name: str, link: str) -> bool:
    if not is_prod():
        logger.info("[email] password reset link for %s: %s", to, _redact_token(link))
    return await _deliver(
        to,
        "password_reset",
        {"name": name, "link": link},
        disable_subscription_tracking=True,
    )


async def send_delete_account_request_email(to: str, name: str, link: str) -> bool:
    """Step 1 — sent as soon as the user asks to delete their account."""
    if not is_prod():
        logger.info("[email] delete-account confirmation link for %s: %s", to, _redact_token(link))
    return await _deliver(
        to,
        "delete_account_request",
        {"name": name, "link": link},
        disable_subscription_tracking=True,
    )


async def send_delete_account_scheduled_email(to: str, name: str, deletion_date: str) -> bool:
    """Step 2 — sent once the password is confirmed and deletion is scheduled."""
    return await _deliver(
        to,
        "delete_account_scheduled",
        {"name": name, "date": deletion_date, "link": "https://www.cancer-bot.com"},
        disable_subscription_tracking=True,
    )


async def send_waitlist_joined_email(to: str, name: str) -> bool:
    """Sent when someone joins the waitlist (MAX_USERS full)."""
    return await _deliver(to, "waitlist_joined", {"name": name})


async def send_waitlist_invited_email(to: str, name: str, link: str) -> bool:
    """Sent when a ninja invites (or re-invites) someone off the waitlist.
    `link` carries the invite token (see src/db/repositories/tokens.py:
    create_waitlist_invite_token) that lets that one email bypass MAX_USERS
    for 48 hours."""
    if not is_prod():
        logger.info("[email] waitlist invite link for %s: %s", to, _redact_token(link))
    return await _deliver(to, "waitlist_invited", {"name": name, "link": link})


async def send_email_change_request_email(to: str, name: str, link: str) -> bool:
    """Step 1 — sent to the account's CURRENT address, proving control of
    it before the user is allowed to pick a new one."""
    if not is_prod():
        logger.info("[email] email-change request link for %s: %s", to, _redact_token(link))
    return await _deliver(to, "email_change_request", {"name": name, "link": link})


async def send_email_change_verification_email(to: str, name: str, old_email: str, link: str) -> bool:
    """Step 2 — sent to the NEW address once it's been submitted, to confirm
    the user actually controls it before the swap takes effect."""
    if not is_prod():
        logger.info("[email] email-change verification link for %s: %s", to, _redact_token(link))
    return await _deliver(to, "email_change_verification", {"name": name, "old_email": old_email, "link": link})


async def send_email_changed_notice_email(to: str, name: str, new_email: str, link: str) -> bool:
    """Step 3 — sent to the OLD address right after the swap completes,
    with a time-limited revert link in case it wasn't the account owner."""
    if not is_prod():
        logger.info("[email] email-change revert link for %s: %s", to, _redact_token(link))
    return await _deliver(to, "email_changed_notice", {"name": name, "new_email": new_email, "link": link})


async def send_delete_account_cancelled_email(to: str, name: str) -> bool:
    """Sent when a scheduled deletion is cancelled (user logs in during the
    7-day grace period and confirms via the cancel-deletion dialog)."""
    return await _deliver(
        to,
        "delete_account_cancelled",
        {"name": name, "link": "https://cancer-bot.com/app"},
        disable_subscription_tracking=True,
    )
