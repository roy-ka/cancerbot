from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID
import logging

from src.deps.db import get_db
from src.deps.auth import get_current_ninja_user
from src.db.repositories.users import list_all_users
from src.db.repositories.conversations import (
    get_conversation_by_id_no_auth,
    get_conversations_list_by_user_id,
)
from src.db.repositories.messeges import get_messages_by_conversation_id
from src.routers.conversations import Message, _process_post_message, _check_message_rate

router = APIRouter(prefix="/ninja", tags=["ninja"])


@router.get("/users/")
async def list_users(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_ninja_user),
):
    users = list_all_users(db=db, limit=limit, offset=offset)
    return {
        "users": [
            {
                "id": str(u.id),
                "name": u.name,
                "email": u.email,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ]
    }


@router.get("/users/{user_id}/conversations/")
async def list_user_conversations(
    user_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_ninja_user),
):
    conversations = get_conversations_list_by_user_id(db=db, user_id=user_id, limit=limit)
    return {
        "conversations": [
            {
                "id": str(conv.id),
                "title": conv.title,
                "updatedAt": conv.updated_at.isoformat() if conv.updated_at else None,
                "lastMessage": conv.last_user_message.get('content') if conv.last_user_message else None,
                "lastMessageTime": conv.last_user_message.get('created_at') if conv.last_user_message else None,
            }
            for conv in conversations
        ]
    }


@router.get("/conversations/{conversation_id}/messages/")
async def get_conversation_messages_ninja(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_ninja_user),
):
    conversation = get_conversation_by_id_no_auth(db=db, conversation_id=conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Ninja sees the full thread — real messages plus any earlier hidden
    # ninja exchanges in this conversation — for debugging continuity.
    messages = get_messages_by_conversation_id(
        db=db,
        conversation_id=conversation_id,
        limit=limit,
        include_hidden=True,
    )

    return {
        "conversation": {
            "id": str(conversation.id),
            "title": conversation.title,
            "updatedAt": conversation.updated_at.isoformat() if conversation.updated_at else None,
        },
        "messages": [
            {
                "id": str(msg.id),
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "sources": msg.sources,
                "hidden_from_user": msg.hidden_from_user,
            }
            for msg in messages
        ],
    }


@router.post("/conversations/{conversation_id}/add_message")
async def post_message_ninja(
    conversation_id: UUID,
    req: Message,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_ninja_user),
):
    if not _check_message_rate(str(current_user.id)):
        raise HTTPException(status_code=429, detail="Too many messages. Please wait before sending another.")

    logging.info("[ninja] posting hidden message into conversation_id=%s ninja=%s", conversation_id, current_user.id)
    return await _process_post_message(
        conversation_id=conversation_id,
        req=req,
        db=db,
        current_user=current_user,
        hidden_from_user=True,
    )
