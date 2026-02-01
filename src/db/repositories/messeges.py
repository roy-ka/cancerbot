from src.db.models import Conversation, Message
import logging


def add_message(db, conversation_id, role, content):
  new_message = Message(conversation_id=conversation_id, role=role, content=content)
  logging.info(f"Adding message to conversation {conversation_id} with role {role}")
  db.add(new_message)
  db.commit()
  return new_message

def get_messages_by_conversation_id(db, conversation_id, limit=50):
  return db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.created_at).limit(limit).all()
