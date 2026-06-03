from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Literal, Optional
from src.deps.db import get_db
from src.deps.auth import get_current_user
import logging
from pydantic import BaseModel
from src.db.repositories.conversations import (
    get_conversation_by_id,
    get_conversation_by_id_no_auth,
    get_conversations_list_by_user_id,
    create_conversation,
    format_last_msg_time,
    soft_delete_conversation,
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
                "updatedAt": conv.updated_at.isoformat() if conv.updated_at else None,
                'lastMessage': conv.last_user_message.get('content') if conv.last_user_message else None,
                'lastMessageTime': conv.last_user_message.get('created_at') if conv.last_user_message else None
            }
            for conv in conversations
        ]
    }


@router.get("/{conversation_id}/messages/")
async def get_conversation_messages(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    limit: int = Query(30, ge=1, le=100),
    before: Optional[str] = Query(None),
):
    logging.info(
        "Fetching paginated messages for conversation_id: %s limit=%s before=%s",
        conversation_id,
        limit,
        before,
    )

    conversation = get_conversation_by_id(
        db=db,
        conversation_id=conversation_id,
        current_user=current_user,
    )

    messages = get_messages_by_conversation_id(
        db=db,
        conversation_id=conversation_id,
        limit=limit,
        before=before,
    )

    next_before = None
    if messages:
        oldest = messages[0]
        if oldest.created_at:
            next_before = f"{oldest.created_at.isoformat()}|{str(oldest.id)}"

    if conversation is None:
        logging.error("couldn't find conversation id: %s", conversation_id)
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Enforce ownership
    if str(conversation.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    messages_data = [
        {
            "id": str(msg.id),
            "role": msg.role,
            "content": msg.content,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "intent": msg.intent,
            "claims": msg.claims,
            "sources": msg.sources,
        }
        for msg in messages
    ]

    return {
        "conversation": {
            "id": str(conversation.id),
            "title": conversation.title,
            "updatedAt": conversation.updated_at.isoformat() if conversation.updated_at else None,
        },
        "messages": messages_data,
        "next_before": next_before,
    }

@router.post("/{conversation_id}/add_message")
async def post_message(
    conversation_id: UUID,
    req: Message,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
    conversation=None,
):
    if conversation is None:
        conversation = get_conversation_by_id_no_auth(db=db, conversation_id=conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
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
    logging.info(f"[conversation] Running retrieval for query: '{req.content}'")
    context = run_retrieval(req.content)
    logging.debug(f"[conversation] Retrieval context: {len(context.get('generation_context', []))} items, sources_ids={context.get('sources_ids')}")

    logging.info(f"[conversation] Generating response with {len(context.get('generation_context', []))} context items")
    response = OllamaConnector.generate_text(
        context=context["generation_context"],
        question=req.content,
        conversation = conversation

    )
    logging.debug(f"[conversation] Generated response ({len(response)} chars)")

    # Store assistant message
    try:
        sources_ids = context.get('sources_ids')
        logging.info(f"[conversation] Storing assistant message with sources_ids={sources_ids}")

        asistent_message = add_message(
            db=db,
            conversation_id=conversation.id,
            role="assistant",
            content=response,
            intent=context.get("intent"),
            claim_ids= context.get('claims_ids'),
            sources_ids= sources_ids
        )
        logging.debug(f"[conversation] Message stored with ID={asistent_message.id}, sources_ids from DB={asistent_message.sources_ids}")

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
            "updatedAt": asistent_message.created_at,
            'lastMessage': user_message.content,
            'lastMessageTime':  format_last_msg_time(user_message.created_at),
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


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    success = soft_delete_conversation(db=db, conversation_id=conversation_id, user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True}