"""Email normalization.

`LowercaseEmail` is the form every account email is stored and looked up
in. `normalize_email_for_dedup` is a much more aggressive canonical form used
for duplicate detection only — never use its output for actually sending
mail, since a provider may treat the un-stripped form as a distinct, real
inbox. It exists purely so "john.doe+promo@gmail.com" and
"johndoe@gmail.com" are recognized as the same person when checking for
existing waitlist/account entries.
"""
from typing import Annotated

from pydantic import AfterValidator, EmailStr

# EmailStr only lowercases the domain. Lowercasing the local part too makes
# "John@x.com" and "john@x.com" one account — and, since login lockout and
# rate-limit keys are built from the submitted email, stops case variants
# from each getting their own fresh attempt budget.
LowercaseEmail = Annotated[EmailStr, AfterValidator(str.lower)]

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
