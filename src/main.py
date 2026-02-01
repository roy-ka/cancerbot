import logging
from fastapi import FastAPI
from src.retrieval import run_retrieval
from pydantic import BaseModel
from src.classes.ollama_connector import OllamaConnector
from src.db import sql
from src.db.session import get_db
from sqlalchemy.orm import Session
from fastapi import Depends
from uuid import UUID
from src.db.repositories.conversations import create_conversation, get_conversation_by_id, get_conversations_list_by_user_id
from src.db.repositories.messeges import add_message, get_messages_by_conversation_id
class RetrieveRequest(BaseModel):
    message: str
    conversation_id: UUID | None = None
    user_id: UUID


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI()

@app.post("/chat/")
async def chat(req: RetrieveRequest, db: Session = Depends(get_db)):
    text = req.message
    if not req.conversation_id:
        return {"error": "conversation_id is required", "status_code": 400}
    logging.info(f"Conversation ID: {req.conversation_id}")
    conversation = get_conversation_by_id(db=db, conversation_id=req.conversation_id)
    with db.begin():
        message = add_message(db=db, conversation_id=conversation.id, role="user", content=text)
        
    context = run_retrieval(req.message)
    
    response = OllamaConnector.generate_text(
        context=context['generation_context'], 
        question=text
    )
    response_text = response + "\n\nSources:\n" + "\n".join(context['generation_context']) 
    with db.begin():
        add_message(db=db, conversation_id=conversation.id, role="assistant", content=response_text)
    return {"response": response_text, "conversation_id": conversation.id}

@app.get("/health/db")
async def health_db(db: Session = Depends(get_db)):
    stmt = sql.select(sql.text("1"))
    with db.begin():
        result = db.execute(stmt)
        return {"status": "ok", "result": [row[0] for row in result]}

@app.get("/debug/conversations/")
async def debug_conversations(db: Session = Depends(get_db)):
    stmt = sql.text("SELECT COUNT(*) FROM conversations")
    with db.begin():
        count = db.execute(stmt).scalar_one()
    return {"conversations_count": int(count)}

@app.get("/conversations/")
async def get_user_conversations(user_id: UUID, limit: int = 10, db: Session = Depends(get_db)):
    conversations = get_conversations_list_by_user_id(db=db, user_id=user_id, limit=limit)
    return {"conversations": [{"id": conv.id, "title": conv.title, "updated_at": conv.updated_at} for conv in conversations]}

@app.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: UUID, db: Session = Depends(get_db),limit: int = 50):
    messages = get_messages_by_conversation_id(db=db, conversation_id=conversation_id, limit=limit)
    messages_data = [{"id": msg.id, "role": msg.role, "content": msg.content, "timestamp": msg.created_at} for msg in messages]
    return {"messages": messages_data}