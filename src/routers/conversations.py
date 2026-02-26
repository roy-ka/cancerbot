from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import Literal, Optional
from src.deps.db import get_db
from src.deps.auth import get_current_user
import time
from typing import Any, Awaitable, Callable, Dict
from pydantic import BaseModel
from src.db.repositories.conversations import (
    get_conversation_by_id,
    get_conversations_list_by_user_id,
    create_conversation,
    format_last_msg_time,
)
from src.db.repositories.messeges import add_message, get_messages_by_conversation_id
from uuid import UUID
from src.retrieval import run_retrieval
from src.classes.ollama_connector import OllamaConnector
from src.routers.conversation_helper import _emit_noop, search_and_embed
import asyncio
ROLLS = Literal['user', 'assistant']


class Message(BaseModel):
    content: str
    conversation_id: UUID | None = None
    timestamp: str | None = None
    role: ROLLS = 'user'


router = APIRouter(prefix="/conversations", tags=["conversations"])


StageEmitter = Callable[[str, Dict[str, Any]], Awaitable[None]]


async def _process_post_message(
    *,
    conversation_id: UUID,
    req: Message,
    db: Session,
    current_user,
    conversation=None,
    emit: StageEmitter = _emit_noop,
):
    t0 = time.time()

    await emit('loading_conversation', {'conversation_id': str(conversation_id)})

    conversation = conversation or get_conversation_by_id(
        db=db,
        conversation_id=conversation_id,
        current_user=current_user,
    )

    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if str(conversation.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    await emit('saving_user_message', {})

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

    await emit('retrieving_context', {})
    context = await asyncio.to_thread(run_retrieval, req.content)
    await emit('building_prompt', {'history_messages': len(getattr(conversation, 'messages', []) or [])})
    await emit('generating_answer', {})

    response = await asyncio.to_thread(
        OllamaConnector.generate_text,
        context=context["generation_context"],
        question=req.content,
        conversation=conversation,
    )
    if response == 'Insufficient evidence in provided context.':
        await emit('fallback_triggered', {'reason': 'insufficient_evidence'})
        fallback_meta = await search_and_embed(conversation, emit=emit)

        await emit(
            're_retrieving_context',
            {
                'indexed': fallback_meta.get('indexed', 0),
                'terms_count': len(fallback_meta.get('terms') or []),
            },
        )
        context = await asyncio.to_thread(run_retrieval, req.content)
        await emit('rebuilding_prompt', {'history_messages': len(getattr(conversation, 'messages', []) or [])})
        await emit('re_generating_answer', {})
        response = await asyncio.to_thread(
            OllamaConnector.generate_text,
            context=context["generation_context"],
            question=req.content,
            conversation=conversation,
        )
        if response == 'Insufficient evidence in provided context.':
            response = (
                "Insufficient evidence in provided context. "
                f"Fallback indexing completed with {fallback_meta.get('indexed', 0)} new sources "
                f"(skipped {fallback_meta.get('skipped', 0)})."
            )
    await emit('saving_assistant_message', {'intent': context.get('intent')})

    try:
        assistant_message = add_message(
            db=db,
            conversation_id=conversation.id,
            role="assistant",
            content=response,
            intent=context.get("intent"),
            claim_ids=context.get('claims_ids'),
            sources_ids=context.get('sources_ids'),
        )

        db.commit()
        db.refresh(assistant_message)
    except Exception:
        db.rollback()
        raise

    took_ms = int((time.time() - t0) * 1000)
    await emit('done', {'took_ms': took_ms})

    def _msg_to_dict(m):
        return {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if getattr(m, 'created_at', None) else None,
            "intent": getattr(m, 'intent', None),
            "claims": getattr(m, 'claims', None),
            "sources": getattr(m, 'sources', None),
        }

    return {
        "messages": [_msg_to_dict(user_message), _msg_to_dict(assistant_message)],
        "conversation": {
            "id": str(conversation.id),
            "title": conversation.title,
            "updatedAt": assistant_message.created_at.isoformat() if getattr(assistant_message, 'created_at', None) else None,
            "lastMessage": user_message.content,
            "lastMessageTime": format_last_msg_time(user_message.created_at),
        },
    }


@router.get("/")
async def get_user_conversations(
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
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
                'lastMessage': conv.last_user_message.get('content') if getattr(conv, 'last_user_message', None) else None,
                'lastMessageTime': conv.last_user_message.get('created_at') if getattr(conv, 'last_user_message', None) else None,
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

    conversation = get_conversation_by_id(
        db=db,
        conversation_id=conversation_id,
        current_user=current_user,
    )

    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if str(conversation.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

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

    messages_data = [
        {
            "id": str(msg.id),
            "role": msg.role,
            "content": msg.content,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "intent": msg.intent,
            "claims": getattr(msg, 'claims', None),
            "sources": getattr(msg, 'sources', None),
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
    current_user=Depends(get_current_user),
    conversation=None,
):
    return await _process_post_message(
        conversation_id=conversation_id,
        req=req,
        db=db,
        current_user=current_user,
        conversation=conversation,
    )


@router.websocket('/{conversation_id}/add_message/ws')
async def post_message_ws(
    websocket: WebSocket,
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await websocket.accept()

    async def emit(stage: str, data: Dict[str, Any] | None = None) -> None:
        await websocket.send_json({
            'type': 'stage',
            'stage': stage,
            'data': data or {},
        })

    try:
        payload = await websocket.receive_json()
        req = Message(**payload)

        await emit('received', {'conversation_id': str(conversation_id)})

        result = await _process_post_message(
            conversation_id=conversation_id,
            req=req,
            db=db,
            current_user=current_user,
            conversation=None,
            emit=emit,
        )

        await websocket.send_json({'type': 'final', **result})
        await websocket.close()

    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await websocket.send_json({'type': 'error', 'message': str(e)})
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass


@router.post("/new")
async def new_conversation(
    req: Message,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    conversation = create_conversation(
        db=db,
        user_id=current_user.id,
        title=(req.content or '')[:20] if req and getattr(req, 'content', None) else None,
    )

    return await _process_post_message(
        conversation_id=conversation.id,
        req=req,
        db=db,
        current_user=current_user,
        conversation=conversation,
    )
