from src.db.models import Message
from src.retrieval.db_connector import dbConnector
import logging
from typing import Optional, Tuple
from datetime import datetime
import uuid
import tldextract

__name__ = 'repositories_messeges'


def _decode_cursor(cursor: str) -> Tuple[datetime, uuid.UUID]:
  """Cursor format: <iso8601>|<uuid>"""
  try:
    ts_str, id_str = cursor.split('|', 1)
    ts = datetime.fromisoformat(ts_str)
    return ts, uuid.UUID(id_str)
  except Exception as e:
    raise ValueError('Invalid cursor format') from e


def add_sources(message: Message):
  src = message.sources_ids or []

  if isinstance(src, str):
    src = [s.strip() for s in src.split(',') if s.strip()]

  if not src:
    return

  def _extract_source_name(url: Optional[str]) -> str:
    if not url:
      return 'unknown'
    try:
      ext = tldextract.extract(str(url))
      return (ext.domain or 'unknown').lower()
    except Exception:
      return 'unknown'

  response = dbConnector.get_sources_by_id(src)
  results = response['hits']['hits']

  sources = []
  for res in results:
    data = res['_source']
    url = data.get('url') or data.get('pmid') or data.get('doi')

    entry = {
      'evidence_score_0_5': data.get('evidence_score_0_5'),
      'text': data.get('content_for_embedding'),
      'id': data.get('id'),
      'url': url,
      'name': _extract_source_name(url),
      'title': data.get('title'),
    }
    sources.append(entry)

  message.sources = sources


def add_message(db, conversation_id, role, content, sources_ids=''):
  new_message = Message(
    conversation_id=conversation_id,
    role=role,
    content=content,
    sources_ids=sources_ids,
  )
  logging.info(f"Adding message to conversation {conversation_id} with role {role}")
  db.add(new_message)
  # Caller is responsible for commit/rollback
  return new_message


def get_recent_messages(db, conversation_id, limit: int = 12):
  """Return the most recent `limit` messages (oldest-first) without resolving citations."""
  rows = (
    db.query(Message)
    .filter(Message.conversation_id == conversation_id)
    .order_by(Message.created_at.desc(), Message.id.desc())
    .limit(limit)
    .all()
  )
  return list(reversed(rows))


def get_messages_by_conversation_id(db, conversation_id, limit=50, before: Optional[str] = None):
  q = db.query(Message).filter(Message.conversation_id == conversation_id)

  # Keyset pagination on (created_at, id): fetch messages strictly older than the cursor
  if before:
    before_ts, before_id = _decode_cursor(before)
    q = q.filter(
      (Message.created_at < before_ts)
      | ((Message.created_at == before_ts) & (Message.id < before_id))
    )

  # Fetch newest -> oldest for stable pagination, then reverse for UI order
  page_desc = (
    q.order_by(Message.created_at.desc(), Message.id.desc())
     .limit(limit)
     .all()
  )
  messages = list(reversed(page_desc))  # oldest -> newest

  for msg in messages:
    if msg.role == 'assistant':
      add_sources(msg)

  return messages
