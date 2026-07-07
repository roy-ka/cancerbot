import asyncio
import logging
import os

logger = logging.getLogger(__name__)

EMAIL_TEMPLATES = {
    "verification": "d-6a6d6095e74549fbb91c18e741cef813",
    # "password_reset": "d-...",
}


def _send_sendgrid(to: str, template_id: str, template_data: dict) -> None:
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, DynamicTemplateData
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


async def send_password_reset_email(to: str, code: str) -> None:
    # TODO: add SendGrid template and move to EMAIL_TEMPLATES
    await asyncio.to_thread(
        _send_sendgrid,
        to,
        "",  # placeholder until template is created
        {"code": code},
    )
