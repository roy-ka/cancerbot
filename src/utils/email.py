import asyncio
import logging
import os
import threading

logger = logging.getLogger(__name__)

EMAIL_TEMPLATES = {
    "verification": "d-6a6d6095e74549fbb91c18e741cef813",
    "password_reset": "d-89a37afdde454f699046dda66cfca385",
    "fallback_alert": "d-18e52d88f49b4b79b4ff292b1074bd75",
    "account_deleted": "d-feba610add7d4ad091351504f1a14937",
    "delete_account_request": "d-4db440ef36e547a0a7e16e35500d935c",
    "delete_account_scheduled": "d-336a3518ba8140cd9b5689f1aab52a94",
}

_FALLBACK_ALERT_TO = "roykazaz@gmail.com"


def _send_sendgrid(
    to: str,
    template_id: str,
    template_data: dict,
    *,
    disable_subscription_tracking: bool = False,
) -> None:
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
        logger.error("[email] SendGrid error: %s", e)
        raise


def send_fallback_alert(model: str) -> None:
    """Fire-and-forget fallback alert — safe to call from sync worker threads."""
    def _send():
        try:
            _send_sendgrid(_FALLBACK_ALERT_TO, EMAIL_TEMPLATES["fallback_alert"], {"model": model})
        except Exception as exc:
            logger.error("[email] fallback alert failed: %s", exc)
    threading.Thread(target=_send, daemon=True).start()


async def send_verification_email(to: str, name: str, token: str, frontend_url: str) -> None:
    verify_url = f"{frontend_url}/verify-email?token={token}"
    if os.getenv("ENV", "development") != "production":
        logger.info("[email] verification link for %s: %s", to, verify_url)
    await asyncio.to_thread(
        _send_sendgrid,
        to,
        EMAIL_TEMPLATES["verification"],
        {"name": name, "link": verify_url},
    )


async def send_account_deleted_email(to: str, name: str) -> None:
    await asyncio.to_thread(
        _send_sendgrid,
        to,
        EMAIL_TEMPLATES["account_deleted"],
        {"name": name},
        disable_subscription_tracking=True,
    )


async def send_password_reset_email(to: str, name: str, link: str) -> None:
    if os.getenv("ENV", "development") != "production":
        logger.info("[email] password reset link for %s: %s", to, link)
    await asyncio.to_thread(
        _send_sendgrid,
        to,
        EMAIL_TEMPLATES["password_reset"],
        {"name": name, "link": link},
        disable_subscription_tracking=True,
    )


async def send_delete_account_request_email(to: str, name: str, link: str) -> None:
    """Step 1 — sent as soon as the user asks to delete their account."""
    if os.getenv("ENV", "development") != "production":
        logger.info("[email] delete-account confirmation link for %s: %s", to, link)
    await asyncio.to_thread(
        _send_sendgrid,
        to,
        EMAIL_TEMPLATES["delete_account_request"],
        {"name": name, "link": link},
        disable_subscription_tracking=True,
    )


async def send_delete_account_scheduled_email(to: str, name: str, deletion_date: str) -> None:
    """Step 2 — sent once the password is confirmed and deletion is scheduled."""
    await asyncio.to_thread(
        _send_sendgrid,
        to,
        EMAIL_TEMPLATES["delete_account_scheduled"],
        {"name": name, "date": deletion_date, "link": "https://www.cancer-bot.com"},
        disable_subscription_tracking=True,
    )
