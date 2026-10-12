"""`LowercaseEmail`: the form every account email is stored and looked up in."""
from typing import Annotated

from pydantic import AfterValidator, EmailStr

# EmailStr only lowercases the domain. Lowercasing the local part too makes
# "John@x.com" and "john@x.com" one account — and, since login lockout and
# rate-limit keys are built from the submitted email, stops case variants
# from each getting their own fresh attempt budget.
LowercaseEmail = Annotated[EmailStr, AfterValidator(str.lower)]
