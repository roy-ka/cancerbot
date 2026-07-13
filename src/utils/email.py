import asyncio
import logging
import os
import threading

logger = logging.getLogger(__name__)

EMAIL_TEMPLATES = {
    "verification": "d-6a6d6095e74549fbb91c18e741cef813",
    "password_reset": "d-89a37afdde454f699046dda66cfca385",
    "fallback_alert": "d-18e52d88f49b4b79b4ff292b1074bd75",
}

_FALLBACK_ALERT_TO = "roykazaz@gmail.com"


def _send_sendgrid(to: str, template_id: str, template_data: dict) -> None:
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
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


async def send_password_reset_email(to: str, name: str, link: str) -> None:
    if os.getenv("ENV", "development") != "production":
        logger.info("[email] password reset link for %s: %s", to, link)
    await asyncio.to_thread(
        _send_sendgrid,
        to,
        EMAIL_TEMPLATES["password_reset"],
        {"name": name, "link": link},
    )
