from datetime import datetime, timezone
from src.db.models import User

def create_user(db, first_name, last_name, email):
  new_user = User(
    first_name=first_name,
    last_name=last_name,
    email=email.lower(),
  )
  db.add(new_user)
  db.commit()
  return new_user

def get_user_by_email(db, email):
  # Stored emails are always lowercase (see migration lowercase_user_emails_001).
  return db.query(User).filter(User.email == email.lower()).first()

def get_user_by_id(db, user_id):
  return db.query(User).filter(User.id == user_id).first()

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