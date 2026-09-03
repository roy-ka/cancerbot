from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID
import logging

from src.deps.db import get_db
from src.deps.auth import get_current_ninja_user
from src.db.repositories.users import list_all_users
from src.db.repositories.waitlist import list_waitlist_entries, get_waitlist_entry_by_id, mark_waitlist_entry_invited
from src.db.repositories.tokens import create_waitlist_invite_token
from src.db.repositories.conversations import (
    get_conversation_by_id_no_auth,
    get_conversations_list_by_user_id,
)
from src.db.repositories.messeges import get_messages_by_conversation_id
from src.routers.conversations import Message, _process_post_message, _check_message_rate
from src.routers.auth import _get_frontend_url
from src.queue import enqueue
from src.utils.utils import is_prod

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
                "first_name": u.first_name,
                "last_name": u.last_name,
                "email": u.email,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ]
    }


@router.get("/waitlist/")
async def list_waitlist(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_ninja_user),
):
    entries = list_waitlist_entries(db=db, limit=limit, offset=offset)
    return {
        "entries": [
            {
                "id": str(e.id),
                "email": e.email,
                "name": e.name,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "invited": e.invited,
                "invited_at": e.invited_at.isoformat() if e.invited_at else None,
            }
            for e in entries
        ]
    }


@router.post("/waitlist/{entry_id}/invite")
async def invite_waitlist_entry(
    entry_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_ninja_user),
):
    """Send (or resend) an invite to one waitlist entry. Generates a fresh
    48h invite token — a resend supersedes any earlier link, which stops
    working immediately (see create_waitlist_invite_token)."""
    entry = get_waitlist_entry_by_id(db=db, entry_id=entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")

    token = create_waitlist_invite_token(db=db, waitlist_entry_id=entry.id)
    link = f"{_get_frontend_url()}/login?invite_token={token}"
    await enqueue("send_waitlist_invited_email_job", to=entry.email, name=entry.name, link=link)
    mark_waitlist_entry_invited(db=db, entry=entry)

    resp = {
        "id": str(entry.id),
        "email": entry.email,
        "name": entry.name,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "invited": entry.invited,
        "invited_at": entry.invited_at.isoformat() if entry.invited_at else None,
    }
    # Dev-mode escape hatch, same pattern as /auth/register/'s
    # verification_token — there's no inbox to read the real link from in
    # tests/CI, and only the hash is stored so it can't be recovered later.
    if not is_prod():
        resp["invite_token"] = token
    return resp


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
