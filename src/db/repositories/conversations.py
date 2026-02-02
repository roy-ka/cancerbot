from src.db.models import Conversation
import logging
def create_conversation(db, user_id, title = None):
  new_conversation = Conversation(
    user_id=user_id,
    title=title
  )
  logging.info(f"Creating conversation for user {user_id} with title {title}")
  db.add(new_conversation)
  db.commit()
  return new_conversation
  
def get_conversation_by_id(db, current_user, conversation_id):
  return db.query(Conversation).filter(Conversation.user_id == current_user.id, Conversation.id == conversation_id).first()

def get_conversations_list_by_user_id(db, user_id, limit=10):
  return db.query(Conversation).filter(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc()).limit(limit).all()