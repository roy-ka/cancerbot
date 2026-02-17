from src.db.models import Message
from src.retrieval.db_connector import dbConnector
import logging

__name__='repositories_messeges'
def add_claims_and_sources(message: Message):
  src = message.sources_ids or []
  clm = message.claim_ids or []

  if isinstance(src, str):
    src = [s.strip() for s in src.split(',') if s.strip()]
  if isinstance(clm, str):
    clm = [s.strip() for s in clm.split(',') if s.strip()]

  ids = [*src, *clm]
  if not ids:
    return
  response = dbConnector.get_claims_and_sources_by_id(ids)
  results = response['hits']['hits']
  claims = []
  sources = []
  for res in results: 
    data = res['_source']
    entry={
      'evidence_score_0_5': data.get('evidence_score_0_5'),
      'text': data.get('content_for_embedding'),
      'id': data.get('id'),
      'url': data.get('url') or data.get('pmid') or data.get('doi')
    }
    logging.info(entry)
    if data.get('index') == 'claims_index':
      claims.append(entry)
      
    elif data.get('index') == 'sources_index':
      sources.append(entry)
    message.claims = claims
    message.sources = sources

def add_message(db, conversation_id, role, content, sources_ids='',claim_ids='', intent=None):
  new_message = Message(
    conversation_id=conversation_id, 
    role=role, 
    content=content, 
    sources_ids= sources_ids,
    claim_ids=claim_ids,
    intent=intent
  )
  logging.info(f"Adding message to conversation {conversation_id} with role {role}")
  db.add(new_message)
  db.commit()
  if role == 'assistant': 
    add_claims_and_sources(new_message)
  return new_message

def get_messages_by_conversation_id(db, conversation_id, limit=50):
  messages = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.created_at).limit(limit).all()  
  for msg in messages:
    if msg.role == 'assistant':
      add_claims_and_sources(msg)
  return messages
