from datetime import datetime, timezone
from src.db.models import User
from src.utils.email_normalize import normalize_email_for_dedup

def create_user(db, first_name, last_name, email, password_hash):
  new_user = User(
    first_name=first_name,
    last_name=last_name,
    email=email,
    password_hash=password_hash
  )
  db.add(new_user)
  db.commit()
  return new_user

def get_user_by_email(db, email):
  return db.query(User).filter(User.email == email).first()

def get_user_by_id(db, user_id):
  return db.query(User).filter(User.id == user_id).first()

def count_all_users(db) -> int:
  return db.query(User).count()

def email_variation_is_registered(db, normalized_email: str) -> bool:
  """Whether any existing user's email normalizes to `normalized_email`
  (dot/plus-tag variations of an already-registered address).

  User.email has no normalized column of its own (unlike WaitlistEntry,
  where the column exists specifically to dedupe signups), so this scans
  every user's email and normalizes in Python rather than querying by an
  indexed column. Fine at this project's current (intentionally
  slow-growth, see MAX_USERS) scale; would need a stored normalized column
  and an indexed lookup if the user table ever grows large.
  """
  for (email,) in db.query(User.email).all():
    if normalize_email_for_dedup(email) == normalized_email:
      return True
  return False

def list_all_users(db, limit: int = 50, offset: int = 0):
  return (
    db.query(User)
    .order_by(User.created_at.desc())
    .offset(offset)
    .limit(limit)
    .all()
  )

def update_last_login(db, user: User) -> None:
  user.last_login = datetime.now(timezone.utc)
  db.commit()

def delete_user(db, user_id) -> bool:
  user = db.query(User).filter(User.id == user_id).first()
  if not user:
    return False
  db.delete(user)
  db.commit()
  return True