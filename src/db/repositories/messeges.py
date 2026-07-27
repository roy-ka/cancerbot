from src.db.models import Message
from src.retrieval.db_connector import dbConnector
import logging
import re
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


def _normalize_source_ids(message: Message) -> list:
  """Return a message's sources_ids as a list, tolerating the legacy CSV form."""
  src = message.sources_ids or []
  if isinstance(src, str):
    src = [s.strip() for s in src.split(',') if s.strip()]
  return src


def _extract_source_name(url: Optional[str]) -> str:
  if not url:
    return 'unknown'
  try:
    ext = tldextract.extract(str(url))
    return (ext.domain or 'unknown').lower()
  except Exception:
    return 'unknown'


def _hit_to_entry(data: dict) -> Tuple[str, dict]:
  """Convert one OpenSearch _source into a (base_id, display entry) pair."""
  # Strip :cN chunk suffix — base ID is the stable identifier
  base_id = re.sub(r':c\d+$', '', data.get('id') or '')

  url = data.get('url') or data.get('pmid') or data.get('doi')

  source_type = data.get('source_type')
  if source_type == 'wikipedia':
    name = data.get('title')
  elif source_type == 'url':
    # Use title if available, otherwise extract the domain from the actual URL
    name = data.get('title') or _extract_source_name(data.get('url'))
  else:
    name = base_id

  return base_id, {
    'evidence_score_0_5': data.get('evidence_score_0_5'),
    'text': data.get('full_text'),
    'id': base_id,
    'url': url,
    'name': name,
    'title': data.get('title'),
    'source_type': source_type,
  }


def add_claims_and_sources_bulk(messages) -> None:
  """Attach `sources`/`claims` to every message in one OpenSearch round trip.

  The per-message variant issues a search each time it's called, so paging a
  conversation used to fire one query per assistant message. Here every
  message's source IDs are looked up together and the results fanned back out
  by base ID, which keeps a page of history at a single query regardless of
  how many assistant turns it holds.
  """
  targets = [(m, _normalize_source_ids(m)) for m in messages]
  targets = [(m, ids) for m, ids in targets if ids]
  if not targets:
    return

  all_ids = list({sid for _, ids in targets for sid in ids})

  try:
    response = dbConnector.get_claims_and_sources_by_id(all_ids)
    results = response['hits']['hits']
  except Exception:
    # dbConnector not available or error occurred (e.g., in tests without OpenSearch)
    logging.warning("Failed to retrieve claims and sources for %d message(s)", len(targets))
    return

  # base_id -> entry, split by which index the hit came from
  sources_by_id: dict = {}
  claims_by_id: dict = {}
  for res in results:
    data = res['_source']
    base_id, entry = _hit_to_entry(data)
    if not base_id:
      continue
    bucket = claims_by_id if 'claims' in res.get('_index', '') else sources_by_id
    # First chunk of a source wins — later chunks carry identical display data
    bucket.setdefault(base_id, entry)

  for message, ids in targets:
    base_ids = [re.sub(r':c\d+$', '', str(sid)) for sid in ids]
    seen: set[str] = set()
    sources = []
    claims = []
    for base_id in base_ids:
      if base_id in seen:
        continue
      seen.add(base_id)
      if base_id in sources_by_id:
        sources.append(sources_by_id[base_id])
      if base_id in claims_by_id:
        claims.append(claims_by_id[base_id])

    # Only set if we found something; don't overwrite with empty lists
    if claims:
      message.claims = claims
    if sources:
      message.sources = sources


def add_claims_and_sources(message: Message):
  add_claims_and_sources_bulk([message])


def add_message(db, conversation_id, role, content, sources_ids='', urls=None, model_name=None, hidden_from_user=False):
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
    hidden_from_user=hidden_from_user,
  )
  db.add(new_message)
  db.commit()

  if role == 'assistant':
    add_claims_and_sources(new_message)

  return new_message


def get_recent_messages(db, conversation_id, limit=50, include_hidden=False):
  q = db.query(Message).filter(Message.conversation_id == conversation_id)
  if not include_hidden:
    q = q.filter(Message.hidden_from_user.is_(False))

  messages = q.order_by(Message.created_at.desc()).limit(limit).all()

  add_claims_and_sources_bulk([m for m in messages if m.role == 'assistant'])

  return messages


def get_messages_by_conversation_id(db, conversation_id, limit=50, before: Optional[str] = None, include_hidden=False):
  q = db.query(Message).filter(Message.conversation_id == conversation_id)
  if not include_hidden:
    q = q.filter(Message.hidden_from_user.is_(False))

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

  add_claims_and_sources_bulk([m for m in messages if m.role == 'assistant'])

  return messages
