from src.db.models import Message
from src.retrieval.db_connector import dbConnector
import logging
import re
from typing import Optional, Tuple
from datetime import datetime, timedelta, timezone
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


# Clinical-trial full_text carries a structured facts line we wrote ourselves in
# src/routers/conversation_helper.py (`Phase: <phases> | Status: <overallStatus>`).
# Parsing our own format lets the UI show a "Trial · Phase · Status" badge without
# indexing phase/status as separate fields (which would need a reindex/backfill).
# Keep these patterns in sync with that writer if its `facts` line ever changes.
# The facts are pipe-separated on one line ("… | Phase: X | Status: Y"), so match
# the label anywhere and stop at the next `|` or line break.
_TRIAL_PHASE_RE = re.compile(r'Phase:\s*(.+?)\s*(?:\||\n|$)')
_TRIAL_STATUS_RE = re.compile(r'Status:\s*(.+?)\s*(?:\||\n|$)')


def _parse_trial_facts(full_text: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
  """Pull (phase, status) out of a clinical-trial source's full_text."""
  if not full_text:
    return None, None
  phase = _TRIAL_PHASE_RE.search(full_text)
  status = _TRIAL_STATUS_RE.search(full_text)
  return (
    phase.group(1).strip() if phase else None,
    status.group(1).strip() if status else None,
  )


def _hit_to_entry(data: dict) -> Tuple[str, dict]:
  """Convert one OpenSearch _source into a (base_id, display entry) pair."""
  # Strip :cN chunk suffix — base ID is the stable identifier
  base_id = re.sub(r':c\d+$', '', data.get('id') or '')

  url = data.get('url') or data.get('pmid') or data.get('doi')

  source_type = data.get('source_type')
  phase = status = None
  if source_type == 'wikipedia':
    name = data.get('title')
  elif source_type == 'url':
    # Use title if available, otherwise extract the domain from the actual URL
    name = data.get('title') or _extract_source_name(data.get('url'))
  elif source_type == 'clinicaltrials':
    # Show the trial's title rather than the raw `nct:NCT…` id, and surface
    # phase/status so the UI can render a distinct trial badge.
    name = data.get('title') or base_id
    phase, status = _parse_trial_facts(data.get('full_text'))
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
    'phase': phase,
    'status': status,
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


def get_message_by_id(db, message_id):
  return db.query(Message).filter(Message.id == message_id).first()


def get_messages_up_to(db, conversation_id, message_id, include_hidden=False):
  """Messages in a conversation from the start up to and including
  `message_id`, oldest-first — the source range for a "split to new
  conversation" copy. Returns [] if message_id isn't found in this
  conversation (e.g. wrong conversation, or hidden and include_hidden=False)."""
  q = db.query(Message).filter(Message.conversation_id == conversation_id)
  if not include_hidden:
    q = q.filter(Message.hidden_from_user.is_(False))
  ordered = q.order_by(Message.created_at.asc(), Message.id.asc()).all()

  cutoff = next((i for i, m in enumerate(ordered) if str(m.id) == str(message_id)), None)
  if cutoff is None:
    return []
  return ordered[: cutoff + 1]


def copy_messages(db, messages, dest_conversation_id) -> list:
  """Insert copies of `messages` (oldest-first) into a different
  conversation, in one transaction. Explicit incrementing `created_at`
  (rather than each row defaulting to "now") keeps the copies in the same
  relative order — ordering elsewhere in this module depends on
  created_at, and inserting a whole batch in a tight loop risks identical
  or out-of-order timestamps otherwise."""
  base_time = datetime.now(timezone.utc)
  copies = []
  for i, m in enumerate(messages):
    copy = Message(
      conversation_id=dest_conversation_id,
      role=m.role,
      content=m.content,
      created_at=base_time + timedelta(milliseconds=i),
      sources_ids=m.sources_ids,
      extracted_terms=m.extracted_terms,
      urls=m.urls,
      model_name=m.model_name,
      hidden_from_user=False,
    )
    db.add(copy)
    copies.append(copy)
  db.commit()
  return copies


def get_recent_messages(db, conversation_id, limit=50, include_hidden=False):
  q = db.query(Message).filter(Message.conversation_id == conversation_id)
  if not include_hidden:
    q = q.filter(Message.hidden_from_user.is_(False))

  messages = q.order_by(Message.created_at.desc()).limit(limit).all()

  add_claims_and_sources_bulk([m for m in messages if m.role == 'assistant'])

  return messages


def get_message_texts_for_summary(db, conversation_id, limit=200):
  """(role, content) pairs for the summarize-conversation feature — plain
  text only, oldest first. Deliberately skips add_claims_and_sources_bulk
  (an OpenSearch round trip) since a summary never needs source objects,
  only what was said. Always excludes hidden_from_user messages, same as
  every other user-facing read path."""
  messages = (
    db.query(Message)
    .filter(Message.conversation_id == conversation_id, Message.hidden_from_user.is_(False))
    .order_by(Message.created_at.asc(), Message.id.asc())
    .limit(limit)
    .all()
  )
  return [(m.role, m.content) for m in messages]


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
