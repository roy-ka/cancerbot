from src.db.models import Conversation, Message
from sqlalchemy import and_, func, select
from sqlalchemy.orm import aliased
from datetime import datetime, timezone
import secrets


def format_last_msg_time(dt):
  if not dt:
    return None

  # Normalize "now" to the timezone of dt when possible
  try:
    now = datetime.now(dt.tzinfo) if getattr(dt, 'tzinfo', None) else datetime.now(timezone.utc)
  except Exception:
    now = datetime.now(timezone.utc)

  try:
    if dt.date() == now.date():
      return dt.strftime('%H:%M')
    days = (now.date() - dt.date()).days
    if days <= 1:
      return '1 day ago'
    return f'{days} days ago'
  except Exception:
    # Fallback to ISO if something unexpected happens
    return dt.isoformat()


def create_conversation(db, user_id, title=None, forked_from_conversation_id=None, forked_from_message_id=None):
  new_conversation = Conversation(
    user_id=user_id,
    title=title,
    forked_from_conversation_id=forked_from_conversation_id,
    forked_from_message_id=forked_from_message_id,
  )
  db.add(new_conversation)
  db.commit()
  return new_conversation


def get_conversation_by_id(db, current_user, conversation_id):
  stmt = select(Conversation).where(
    Conversation.id == conversation_id,
    Conversation.user_id == current_user.id,
    Conversation.deleted_at.is_(None),
  )

  conversation = db.scalars(stmt).one_or_none()
  if conversation is None:
    return None

  return conversation


def get_conversation_by_id_no_auth(db, conversation_id):
  stmt = select(Conversation).where(
    Conversation.id == conversation_id,
    Conversation.deleted_at.is_(None),
  )
  return db.scalars(stmt).one_or_none()


def soft_delete_conversation(db, conversation_id, user_id):
  stmt = select(Conversation).where(
    Conversation.id == conversation_id,
    Conversation.user_id == user_id,
    Conversation.deleted_at.is_(None),
  )
  conversation = db.scalars(stmt).one_or_none()
  if conversation is None:
    return False

  conversation.deleted_at = datetime.now(timezone.utc)
  db.commit()
  return True


def set_use_profile_context(db, conversation_id, user_id, use_profile_context: bool):
  stmt = select(Conversation).where(
    Conversation.id == conversation_id,
    Conversation.user_id == user_id,
    Conversation.deleted_at.is_(None),
  )
  conversation = db.scalars(stmt).one_or_none()
  if conversation is None:
    return None

  conversation.use_profile_context = use_profile_context
  db.commit()
  db.refresh(conversation)
  return conversation


def enable_share(db, conversation_id, user_id):
  """Idempotent: returns the existing token if sharing is already on,
  otherwise mints a fresh one. Returns None if the conversation doesn't
  exist / isn't owned by user_id / is deleted."""
  stmt = select(Conversation).where(
    Conversation.id == conversation_id,
    Conversation.user_id == user_id,
    Conversation.deleted_at.is_(None),
  )
  conversation = db.scalars(stmt).one_or_none()
  if conversation is None:
    return None

  if not conversation.share_token:
    conversation.share_token = secrets.token_urlsafe(32)
    db.commit()
    db.refresh(conversation)

  return conversation.share_token


def disable_share(db, conversation_id, user_id):
  """Revokes sharing (clears the token) if it was set. Returns False if the
  conversation doesn't exist / isn't owned by user_id / is deleted."""
  stmt = select(Conversation).where(
    Conversation.id == conversation_id,
    Conversation.user_id == user_id,
    Conversation.deleted_at.is_(None),
  )
  conversation = db.scalars(stmt).one_or_none()
  if conversation is None:
    return False

  conversation.share_token = None
  db.commit()
  return True


def get_conversation_by_share_token(db, share_token):
  """Public (unauthenticated) lookup — a deleted conversation's link 404s
  naturally via the deleted_at filter, no separate cleanup needed when a
  shared conversation gets soft-deleted."""
  stmt = select(Conversation).where(
    Conversation.share_token == share_token,
    Conversation.deleted_at.is_(None),
  )
  return db.scalars(stmt).one_or_none()


def get_conversations_list_by_user_id(db, user_id, limit=10):
  # Subquery: latest message timestamp per conversation (any role)
  last_msg_ts_sq = (
    db.query(
      Message.conversation_id.label('conversation_id'),
      func.max(Message.created_at).label('last_created_at'),
    )
    .group_by(Message.conversation_id)
    .subquery()
  )

  # Subquery: latest user message timestamp per conversation (for display)
  last_user_ts_sq = (
    db.query(
      Message.conversation_id.label('conversation_id'),
      func.max(Message.created_at).label('last_created_at'),
    )
    .filter(Message.role == 'user')
    .group_by(Message.conversation_id)
    .subquery()
  )

  LastMsg = aliased(Message)

  rows = (
    db.query(Conversation, LastMsg)
    .filter(
      Conversation.user_id == user_id,
      Conversation.deleted_at.is_(None),
    )
    .outerjoin(last_msg_ts_sq, last_msg_ts_sq.c.conversation_id == Conversation.id)
    .outerjoin(last_user_ts_sq, last_user_ts_sq.c.conversation_id == Conversation.id)
    .outerjoin(
      LastMsg,
      and_(
        LastMsg.conversation_id == Conversation.id,
        LastMsg.role == 'user',
        LastMsg.created_at == last_user_ts_sq.c.last_created_at,
      ),
    )
    .order_by(last_msg_ts_sq.c.last_created_at.desc().nullslast())
    .limit(limit)
    .all()
  )

  conversations = []
  for convo, last_msg in rows:
    if last_msg is not None:
      setattr(
        convo,
        'last_user_message',
        {
          'id': str(last_msg.id),
          'content': last_msg.content,
          'created_at': format_last_msg_time(last_msg.created_at),
        },
      )
    else:
      setattr(convo, 'last_user_message', None)

    conversations.append(convo)

  return conversations