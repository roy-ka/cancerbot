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


def add_claims_and_sources(message: Message):
  src = message.sources_ids or []

  if isinstance(src, str):
    src = [s.strip() for s in src.split(',') if s.strip()]

  ids = src
  if not ids:
    return

  def _extract_source_name(url: Optional[str]) -> str:
    if not url:
      return 'unknown'
    try:
      ext = tldextract.extract(str(url))
      return (ext.domain or 'unknown').lower()
    except Exception:
      return 'unknown'

  try:
    response = dbConnector.get_claims_and_sources_by_id(ids)
    results = response['hits']['hits']
  except Exception:
    # dbConnector not available or error occurred (e.g., in tests without OpenSearch)
    logging.warning(f"Failed to retrieve claims and sources for message {message.id}")
    return

  claims = []
  sources = []
  seen_source_ids: set[str] = set()
  for res in results:
    data = res['_source']
    # Deduplicate: one entry per source_id (avoid multiple chunks of the same doc)
    dedup_key = data.get('source_id') or data.get('id') or ''
    if dedup_key in seen_source_ids:
      continue
    seen_source_ids.add(dedup_key)

    url = data.get('url') or data.get('pmid') or data.get('doi')

    # Use title for Wikipedia sources, otherwise use the stable id
    name = data.get('title') if data.get('source_type') == 'wikipedia' else data.get('id')

    entry = {
      'evidence_score_0_5': data.get('evidence_score_0_5'),
      'text': data.get('content_for_embedding'),
      'id': data.get('id'),
      'url': url,
      'name': name,
      'title': data.get('title'),
      'source_type': data.get('source_type'),
    }
    if data.get('index') == 'claims_index':
      claims.append(entry)
    elif data.get('index') == 'sources_index':
      sources.append(entry)

  # Only set if we found something; don't overwrite with empty lists
  if claims:
    message.claims = claims
  if sources:
    message.sources = sources


def add_message(db, conversation_id, role, content, sources_ids='', urls=None, model_name=None):
  # Convert string sources_ids to lists for JSON column compatibility
  if isinstance(sources_ids, str):
    sources_ids = [s.strip() for s in sources_ids.split(',') if s.strip()] if sources_ids else []

  new_message = Message(
    conversation_id=conversation_id,
    role=role,
    content=content,
    sources_ids=sources_ids if sources_ids else None,
    urls=urls if urls else None,
    model_name=model_name if role == 'assistant' else None,
  )
  db.add(new_message)
  db.commit()

  if role == 'assistant':
    add_claims_and_sources(new_message)

  return new_message


def get_recent_messages(db, conversation_id, limit=50):
  messages = (
    db.query(Message)
    .filter(Message.conversation_id == conversation_id)
    .order_by(Message.created_at.desc())
    .limit(limit)
    .all()
  )

  for msg in messages:
    if msg.role == 'assistant':
      add_claims_and_sources(msg)

  return messages


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
      add_claims_and_sources(msg)

  return messages
