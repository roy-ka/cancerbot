import asyncio
import logging
import os

logger = logging.getLogger(__name__)


def _send_sendgrid(to: str, subject: str, html: str) -> None:
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
    except ImportError:
        logger.error("SendGrid SDK not installed. Run: pip install sendgrid")
        return

    api_key = os.getenv("SENDGRID_API_KEY")
    if not api_key:
        logger.warning("[email] SendGrid not configured — would have sent to %s: %s", to, subject)
        return

    from_email = os.getenv("EMAIL_FROM", "noreply@example.com")
    from_name = os.getenv("EMAIL_FROM_NAME", "CancerBot")

    message = Mail(
        from_email=(from_email, from_name),
        to_emails=to,
        subject=subject,
        html_content=html,
    )

    try:
        sg = SendGridAPIClient(api_key)
        sg.send(message)
        logger.info("[email] sent to=%s subject=%s", to, subject)
    except Exception as e:
        logger.error("[email] SendGrid error: %s", e)
        raise


async def send_password_reset_email(to: str, code: str) -> None:
    subject = "Your CancerBot password reset code"
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto">
      <h2>Reset your password</h2>
      <p>Enter this 6-digit code to reset your password. It expires in 15 minutes.</p>
      <div style="font-size:36px;font-weight:bold;letter-spacing:10px;text-align:center;
                  background:#f4f4f4;padding:20px;border-radius:8px;margin:24px 0">
        {code}
      </div>
      <p style="color:#888;font-size:13px">
        If you did not request this, you can safely ignore this email.
      </p>
    </div>
    """
    await asyncio.to_thread(_send_sendgrid, to, subject, html)
