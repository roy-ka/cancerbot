from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import Literal, Optional, Dict, Any, Awaitable, Callable
from src.deps.db import get_db
from src.deps.auth import get_current_user
import logging
import time
import asyncio
import os
from pydantic import BaseModel, field_validator
from src.db.repositories.conversations import (
    get_conversation_by_id,
    get_conversation_by_id_no_auth,
    get_conversations_list_by_user_id,
    create_conversation,
    format_last_msg_time,
    soft_delete_conversation,
)
from src.db.repositories.messeges import add_message, add_claims_and_sources, get_messages_by_conversation_id, get_recent_messages
from uuid import UUID
from src.retrieval import run_retrieval
from src.classes.ollama_connector import OllamaConnector
from src.routers.conversation_helper import _emit_noop, search_and_embed, fetch_url_contents

ROLLS = Literal['user', 'assistant']

class Message(BaseModel):
    content: str
    conversation_id: UUID | None = None
    timestamp: str | None = None
    role: ROLLS = 'user'
    urls: list[str] | None = None  # URLs detected in the message by the client

    @field_validator('urls')
    @classmethod
    def validate_urls(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(v) > 5:
            raise ValueError('Too many URLs (max 5)')
        for url in v:
            if not url.startswith(('http://', 'https://')):
                raise ValueError(f'Only http/https URLs are accepted')
        return v

StageEmitter = Callable[[str, Dict[str, Any] | None], Awaitable[None]]

async def _emit_stage_noop(stage: str, data: Dict[str, Any] | None = None) -> None:
    pass

router = APIRouter(prefix="/conversations", tags=["conversations"])


async def _process_post_message(
    *,
    conversation_id: UUID,
    req: Message,
    db: Session,
    current_user,
    conversation=None,
    emit: StageEmitter = _emit_stage_noop,
):
    t0 = time.time()

    logging.info(f"[conversation] Processing message for conversation {conversation_id}, user {current_user.id}")
    logging.info(f"[conversation] Message content: {req.content[:100]}")

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

    logging.info(f"[conversation] Conversation verified, conversation_id={conversation.id}")
    await emit('saving_user_message', {})

    try:
        user_message = add_message(
            db=db,
            conversation_id=conversation.id,
            role="user",
            content=req.content,
            urls=req.urls,
        )
        db.commit()
        db.refresh(user_message)
        db.refresh(conversation)
    except Exception:
        db.rollback()
        raise

    # Extract and save scientific terms for the new message
    try:
        nlp_url = os.getenv("NLP_URL", "http://127.0.0.1:8011").strip().strip("\"'")
        import httpx
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            from src.routers.conversation_helper import _extract_terms_from_message
            extracted_terms = await _extract_terms_from_message(client, nlp_url, req.content)
            user_message.extracted_terms = extracted_terms if extracted_terms else None
            db.add(user_message)
            db.commit()
            logging.info(f"[conversation] Extracted and saved {len(extracted_terms)} terms for message {user_message.id}")
    except Exception as e:
        logging.warning(f"[conversation] Failed to extract terms for message: {type(e).__name__}: {e}")
        db.rollback()

    await emit('fallback_triggered', {'reason': 'always_search_external'})
    search_meta = await search_and_embed(conversation, emit=emit)
    logging.info(f"[conversation] External search and indexing complete: indexed={search_meta.get('indexed')}, skipped={search_meta.get('skipped')}")

    # Record external search results using the current db session
    external_data = search_meta.get('external_search_data', {})
    if external_data:
        try:
            from src.db.models import ExternalSearchResult
            original_query = external_data.get('original_query', '')
            conv_id = external_data.get('conversation_id')
            msg_id = external_data.get('message_id')
            extracted_terms = external_data.get('extracted_terms', [])

            for source_type in ['pubmed', 'crossref', 'wikipedia']:
                results = external_data.get(f'{source_type}_sources', [])
                logging.info(f"[conversation] Recording external search: {source_type}={len(results)} results")

                top_title = None
                top_url = None
                if results:
                    first = results[0]
                    top_title = first.get("title") or first.get("pmid") or first.get("doi")
                    top_url = first.get("url")

                record = ExternalSearchResult(
                    conversation_id=conv_id,
                    message_id=msg_id,
                    search_query=original_query[:500],
                    source=source_type,
                    extracted_terms=",".join(extracted_terms) if extracted_terms else None,
                    result_count=len(results),
                    indexed_count=len(results),
                    skipped_count=0,
                    top_result_title=str(top_title)[:500] if top_title else None,
                    top_result_url=str(top_url)[:500] if top_url else None,
                )
                db.add(record)
            db.commit()
            logging.info(f"[conversation] Successfully recorded external search results")
        except Exception as e:
            logging.error(f"[conversation] Failed to record external search results: {type(e).__name__}: {e}")
            import traceback
            logging.error(f"[conversation] Traceback: {traceback.format_exc()}")
            db.rollback()

    await emit('retrieving_context', {})
    logging.info(f"[conversation] Retrieving context for query: {req.content[:100]}")
    context = await asyncio.to_thread(run_retrieval, req.content)
    logging.info(f"[conversation] Retrieved {len(context.get('sources_ids', []))} sources, {len(context.get('claims_ids', []))} claims")

    if req.urls:
        logging.info(f"[conversation] Fetching {len(req.urls)} user-provided URL(s)")
        url_items = await fetch_url_contents(req.urls)
        if url_items:
            logging.info(f"[conversation] Fetched {len(url_items)} URL(s) successfully, prepending to context")
            context['generation_context'] = url_items + context['generation_context']
            context['sources_ids'] = [item['id'] for item in url_items] + context.get('sources_ids', [])

    max_history = int(os.getenv('PROMPT_MAX_HISTORY', '8'))
    history = get_recent_messages(db, conversation.id, limit=max_history)
    logging.info(f"[conversation] Loaded {len(history)} history messages")

    await emit('building_prompt', {'history_messages': len(history)})
    await emit('generating_answer', {})

    logging.info(f"[conversation] Generating answer with {len(context.get('generation_context', ''))} chars of context")
    response = await asyncio.to_thread(
        OllamaConnector.generate_text,
        context=context["generation_context"],
        question=req.content,
        history=history,
    )
    logging.info(f"[conversation] Generated response: {response[:100]}")

    # Record analytics for search
    try:
        from src.db.models import SearchAnalytic
        metrics = context.get('search_metrics', {})
        logging.info(f"[analytics] Recording search analytics: conversation_id={conversation.id}, message_id={user_message.id}")
        logging.info(f"[analytics] Metrics from context: {metrics}")
        analytic = SearchAnalytic(
            conversation_id=conversation.id,
            message_id=user_message.id,
            search_query=req.content[:500],
            result_count=metrics.get('result_count', 0),
            top_score=metrics.get('top_score'),
            avg_score=metrics.get('avg_score'),
            min_score=metrics.get('min_score'),
            sufficient_evidence=1 if not response.startswith('Insufficient evidence in provided context.') else 0,
            fallback_triggered=0,
        )
        logging.info(f"[analytics] Created SearchAnalytic: result_count={analytic.result_count}, top_score={analytic.top_score}")
        db.add(analytic)
        db.commit()
        logging.info(f"[analytics] Successfully recorded search analytics")
    except Exception as e:
        logging.error(f"[analytics] Failed to record analytics: {type(e).__name__}: {e}")
        import traceback
        logging.error(f"[analytics] Traceback: {traceback.format_exc()}")
        db.rollback()
    await emit('saving_assistant_message', {})

    try:
        assistant_message = add_message(
            db=db,
            conversation_id=conversation.id,
            role="assistant",
            content=response,
            sources_ids=context.get('sources_ids'),
        )

        db.commit()
        db.refresh(assistant_message)
    except Exception:
        db.rollback()
        raise

    add_claims_and_sources(assistant_message)

    took_ms = int((time.time() - t0) * 1000)
    await emit('done', {'took_ms': took_ms})

    def _msg_to_dict(m):
        return {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if getattr(m, 'created_at', None) else None,
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
        # Wait for client to close — avoids racing a CLOSE frame against the final message
        try:
            await websocket.receive()
        except WebSocketDisconnect:
            pass

    except WebSocketDisconnect:
        return
    except Exception as e:
        logging.getLogger(__name__).exception("WebSocket error for conversation %s", conversation_id)
        try:
            await websocket.send_json({'type': 'error', 'message': 'An internal error occurred'})
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