"""Brevo transactional email transport — the active email provider.

Mirrors _send_sendgrid's contract in email.py (dev-mode short-circuit, raises
on failure so _deliver can decide a background task must not crash) but sends
raw HTML built from src/utils/email_templates.py rather than a provider-hosted
template, since Brevo's dashboard template editor isn't used here.
"""
import logging
import os

import requests

from src.utils.utils import is_prod

logger = logging.getLogger(__name__)

_BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
_FROM_EMAIL = "no-reply@cancer-bot.com"
_FROM_NAME = "CancerBot"


def _send_brevo(to: str, subject: str, html: str) -> None:
  # Outside production, never hand anything to Brevo — just log that a send
  # was attempted. Dev/CI has no business delivering real mail. Keyed off
  # is_prod(), so a *staging* deploy also stops sending; give staging its own
  # flag if it ever needs real delivery. The rendered HTML itself is not
  # logged here (a multi-KB blob per line is not useful) — the six public
  # send_* wrappers in email.py already log a redacted, human-readable link
  # for local dev visibility.
  if not is_prod():
    logger.info("[email] dev mode — not sending. to=%s subject=%s", to, subject)
    return

  api_key = os.getenv("BREVO_API_KEY")
  if not api_key:
    logger.warning("[email] Brevo not configured — would have sent to %s (subject=%s)", to, subject)
    return

  try:
    resp = requests.post(
      _BREVO_API_URL,
      headers={
        "api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
      },
      json={
        "sender": {"email": _FROM_EMAIL, "name": _FROM_NAME},
        "to": [{"email": to}],
        "subject": subject,
        "htmlContent": html,
      },
      timeout=10,
    )
    resp.raise_for_status()
    logger.info("[email] sent to=%s subject=%s", to, subject)
  except Exception as e:
    # Raises on purpose: this is the low-level call, and _deliver() in
    # email.py is what decides that a delivery failure must not escape a
    # background task.
    logger.error("[email] Brevo error to=%s subject=%s: %s", to, subject, e)
    raise
