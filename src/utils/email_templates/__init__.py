"""Email bodies sent via Brevo (src/utils/email_brevo.py).

Content lives here in the repo rather than in a provider dashboard (unlike the
dormant SendGrid path in email.py, whose commented-out SENDGRID_EMAIL_TEMPLATES
are opaque IDs pointing at templates stored in SendGrid) — fully
version-controlled and testable, and portable to any future provider.

One module per email (`verification.py`, `password_reset.py`, ...), each
exposing a plain `SUBJECT` string and `HTML` string. This module just
collects them into `TEMPLATES` and renders.

Placeholders are plain str.format() fields (`{name}`, `{link}`, `{date}`,
`{model}`), ported from the original SendGrid Handlebars source
(`{{name}}` -> `{name}`, `{{{link}}}` -> `{link}`, double vs. triple brace
distinguishing "HTML-escape this" from "this is a URL, don't"). `name` is the
only field that ever carries user-supplied text (a registrant's own name), so
it's the only one HTML-escaped in `render()` below — SendGrid's `{{name}}`
did this automatically; now that we render the HTML ourselves, that has to
happen on our side.
"""
import html as _html

from . import (
    verification,
    password_reset,
    account_deleted,
    delete_account_request,
    delete_account_scheduled,
    delete_account_cancelled,
    fallback_alert,
    waitlist_joined,
    waitlist_invited,
    daily_admin_digest,
    weekly_admin_digest,
)

TEMPLATES = {
  "verification": {
    "subject": verification.SUBJECT,
    "html": verification.HTML,
  },
  "password_reset": {
    "subject": password_reset.SUBJECT,
    "html": password_reset.HTML,
  },
  "account_deleted": {
    "subject": account_deleted.SUBJECT,
    "html": account_deleted.HTML,
  },
  "delete_account_request": {
    "subject": delete_account_request.SUBJECT,
    "html": delete_account_request.HTML,
  },
  "delete_account_scheduled": {
    "subject": delete_account_scheduled.SUBJECT,
    "html": delete_account_scheduled.HTML,
  },
  "delete_account_cancelled": {
    "subject": delete_account_cancelled.SUBJECT,
    "html": delete_account_cancelled.HTML,
  },
  "fallback_alert": {
    "subject": fallback_alert.SUBJECT,
    "html": fallback_alert.HTML,
  },
  "waitlist_joined": {
    "subject": waitlist_joined.SUBJECT,
    "html": waitlist_joined.HTML,
  },
  "waitlist_invited": {
    "subject": waitlist_invited.SUBJECT,
    "html": waitlist_invited.HTML,
  },
  "daily_admin_digest": {
    "subject": daily_admin_digest.SUBJECT,
    "html": daily_admin_digest.HTML,
  },
  "weekly_admin_digest": {
    "subject": weekly_admin_digest.SUBJECT,
    "html": weekly_admin_digest.HTML,
  },
}


def render(template_key: str, **fields) -> tuple[str, str]:
  """Return (subject, rendered_html) for a template key.

  `name` is HTML-escaped if present (the only field ever carrying user
  text); `link`/`date`/`model` are substituted as-is, matching the original
  SendGrid Handlebars source's double-vs-triple-brace distinction.
  """
  entry = TEMPLATES[template_key]
  safe_fields = dict(fields)
  if isinstance(safe_fields.get("name"), str):
    safe_fields["name"] = _html.escape(safe_fields["name"])
  return entry["subject"].format(**fields), entry["html"].format(**safe_fields)
