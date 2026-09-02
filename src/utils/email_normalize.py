"""Canonical email form used for duplicate detection only.

Never use the output of this for actually sending mail — a provider may
treat the un-stripped form as a distinct, real inbox. This exists purely so
"john.doe+promo@gmail.com" and "johndoe@gmail.com" are recognized as the
same person when checking for existing waitlist/account entries.
"""

_GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}


def normalize_email_for_dedup(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email:
        return email
    local, domain = email.rsplit("@", 1)
    local = local.split("+", 1)[0]  # plus-tag stripped regardless of provider
    if domain in _GMAIL_DOMAINS:
        local = local.replace(".", "")  # Gmail ignores dots in the local part
        domain = "gmail.com"  # googlemail.com is the same inbox as gmail.com
    return f"{local}@{domain}"
