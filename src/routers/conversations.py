from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Literal
from src.deps.db import get_db
from src.deps.auth import get_current_user
import logging
from pydantic import BaseModel
from src.db.repositories.conversations import (
    get_conversation_by_id,
    get_conversations_list_by_user_id,
    create_conversation
)
from src.db.repositories.messeges import add_message, get_messages_by_conversation_id
from uuid import UUID
from src.retrieval import run_retrieval
from src.classes.ollama_connector import OllamaConnector

ROLLS = Literal['user', 'assistant']

class Message(BaseModel):
    content: str
    conversation_id: UUID | None = None  # "new" for new conversation, or existing conversation ID
    timestamp: str | None = None  # Optional timestamp for retrieval context (e.g. "2024-01-01T00:00:00Z")
    role: ROLLS = 'user'  # Role of the message sender, default to 'user'

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/")
async def get_user_conversations(
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    logging.info(f"Fetching conversations for user_id: {current_user.id} with limit: {limit}")
    conversations = get_conversations_list_by_user_id(
        db=db,
        user_id=current_user.id,
        limit=limit,
    )
    return {
        "conversations": [
            {
                "id": str(conv.id),
                "title": conv.title,
                "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
            }
            for conv in conversations
        ]
    }


@router.get("/{conversation_id}/messages/")
async def get_conversation_messages(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    limit: int = 50,
):
    logging.info(f"Fetching messages for conversation_id: {conversation_id} with limit: {limit}")
    conversation = get_conversation_by_id(db=db, conversation_id=conversation_id, current_user=current_user)
    if conversation is None:
        logging.error("couldn't find conversation id: ", conversation_id)
        raise HTTPException(status_code=404, detail="Conversation not found")

    if str(conversation.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    messages = get_messages_by_conversation_id(
        db=db,
        conversation_id=conversation_id,
        limit=limit,
    )

    messages_data = [
        {
            "id": str(msg.id),
            "role": msg.role,
            "content": msg.content,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            'intent':msg.intent,
            'claims': msg.claims,
            'sources': msg.sources
        }
        for msg in messages
    ]

    return {"conversation": conversation, "messages": messages_data}

@router.post("/{conversation_id}/add_message")
async def post_message(
    conversation_id: UUID,
    req: Message,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
    conversation=None,
):
    conversation = conversation or get_conversation_by_id(
        db=db,
        conversation_id=conversation_id,
        current_user=current_user,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Enforce ownership
    if str(conversation.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        user_message = add_message(
            db=db,
            conversation_id=conversation.id,
            role="user",
            content=req.content,
        )
        db.commit()
        db.refresh(user_message)
    except Exception:
        db.rollback()
        raise

    # Retrieval + generation outside DB tx
    context = run_retrieval(req.content)
    response = OllamaConnector.generate_text(
        context=context["generation_context"],
        question=req.content,
    )

    # Store assistant message
    try:
        asistent_message = add_message(
            db=db,
            conversation_id=conversation.id,
            role="assistant",
            content=response,
            intent=context.get("intent"),
            claim_ids= context.get('claims_ids'),
            sources_ids= context.get('sources_ids')
        )

        db.commit()
        db.refresh(asistent_message)
    except Exception:
        db.rollback()
        raise
    return {
        "messages": [user_message, asistent_message], 
        "conversation": {
            "id": str(conversation.id), 
            "title": conversation.title,
            "updated_at": asistent_message.created_at,
            }
        }

@router.post("/new")
async def new_conversation(    
    req: Message,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    conversation = create_conversation(db=db, user_id=current_user.id, title=req.content[:20])
    return await post_message(
        conversation_id=conversation.id,
        req=req,
        db=db,
        current_user=current_user,
        conversation=conversation,
    )