from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import Literal, Optional, Dict, Any, Awaitable, Callable, Union
from src.deps.db import get_db
from src.deps.auth import get_current_user
import logging
import time
import asyncio
import os
from collections import defaultdict
from pydantic import BaseModel, Field, field_validator
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
from src.classes.ollama_connector import OllamaConnector, NO_DATA_RESPONSE
from src.routers.conversation_helper import _emit_noop, search_and_embed, fetch_url_contents, _representative_terms

ROLLS = Literal['user', 'assistant']

_user_msg_times: dict[str, list[float]] = defaultdict(list)
_MSG_RATE_WINDOW = 60.0
_MSG_RATE_MAX = 10

def _check_message_rate(user_id: str) -> bool:
    now = time.monotonic()
    cutoff = now - _MSG_RATE_WINDOW
    times = _user_msg_times[user_id]
    times[:] = [t for t in times if t > cutoff]
    if len(times) >= _MSG_RATE_MAX:
        return False
    times.append(now)
    return True

_active_ws: dict[str, int] = defaultdict(int)
_WS_MAX_PER_USER = 3

class Message(BaseModel):
    content: str = Field(..., max_length=4000)
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
SendToken = Callable[[str], Awaitable[None]]

async def _emit_stage_noop(stage: str, data: Dict[str, Any] | None = None) -> None:
    pass

async def _send_token_noop(token: str) -> None:
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
    send_token: SendToken = _send_token_noop,
):
    t0 = time.time()

    logging.info(f"[conversation] msg conversation_id={conversation_id} user={current_user.id}")

    await emit('loading_conversation', {'conversation_id': str(conversation_id)})

    if conversation is None:
        conversation = get_conversation_by_id_no_auth(
            db=db,
            conversation_id=conversation_id,
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
        from src.routers.conversation_helper import _extract_terms_from_message
        extracted_terms = await _extract_terms_from_message(req.content)
        logging.info("[conversation] extracted_terms for message %s: %s", user_message.id, extracted_terms)
        user_message.extracted_terms = extracted_terms if extracted_terms else None
        db.add(user_message)
        db.commit()
        logging.info("[conversation] saved extracted_terms=%s to message %s", user_message.extracted_terms, user_message.id)
    except Exception as e:
        logging.warning(f"[conversation] term extraction failed: {type(e).__name__}: {e}")
        db.rollback()

    await emit('fallback_triggered', {'reason': 'always_search_external'})
    search_meta = await search_and_embed(conversation, emit=emit)

    # Backfill extracted_terms on the user message if NLP returned empty (e.g. short
    # abbreviation like "gbm") but search_and_embed produced fallback terms.
    actual_terms = search_meta.get('terms', [])
    if actual_terms and not user_message.extracted_terms:
        try:
            user_message.extracted_terms = actual_terms
            db.add(user_message)
            db.commit()
            logging.info(
                "[conversation] backfilled extracted_terms=%s on message %s",
                actual_terms,
                user_message.id,
            )
        except Exception as e:
            logging.warning("[conversation] backfill extracted_terms failed: %s: %s", type(e).__name__, e)
            db.rollback()

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
        except Exception:
            logging.exception("[conversation] Failed to record external search results")
            db.rollback()

    await emit('retrieving_context', {})

    # If URLs were detected in the message content, use the fetched page title as the
    # retrieval query so KNN/BM25 can find semantically related sources instead of
    # searching with a meaningless URL string.
    url_context_items: list[dict] = search_meta.get('url_context_items', [])
    # Prefer extracted terms as retrieval query so BM25/KNN search on the
    # medical concepts rather than the raw message (which may contain noise
    # words like "tell" that skew BM25 toward unrelated indexed documents).
    # When distinct entities are known (e.g. a drug and a disease), use one
    # representative term per entity rather than the fully synonym-expanded
    # list — otherwise a heavily-synonymed entity (5 GBM synonyms) dominates
    # the BM25/KNN match and buries a newly-indexed source that's actually
    # about both entities under long-established single-entity literature.
    extracted_query_terms = search_meta.get('terms', [])
    entity_groups = search_meta.get('entity_groups', [])
    retrieval_terms = _representative_terms(entity_groups, extracted_query_terms)
    retrieval_query = ' '.join(retrieval_terms) if retrieval_terms else req.content
    if url_context_items:
        first_title = (url_context_items[0].get('title') or '').strip()
        if first_title and first_title != req.content:
            retrieval_query = first_title

    context = await asyncio.to_thread(run_retrieval, retrieval_query)
    logging.info(f"[conversation] retrieved sources={len(context.get('sources_ids', []))} url_ctx={len(url_context_items)}")

    # Prepend URL context items (fetched from message content) directly to generation context
    if url_context_items:
        context['generation_context'] = url_context_items + context['generation_context']
        context['sources_ids'] = [item['id'] for item in url_context_items] + context.get('sources_ids', [])

    if req.urls:
        url_items = await fetch_url_contents(req.urls)
        if url_items:
            context['generation_context'] = url_items + context['generation_context']
            context['sources_ids'] = [item['id'] for item in url_items] + context.get('sources_ids', [])

    max_history = int(os.getenv('PROMPT_MAX_HISTORY', '8'))
    history = get_recent_messages(db, conversation.id, limit=max_history)

    await emit('building_prompt', {'history_messages': len(history)})
    await emit('generating_answer', {})

    try:
        raw_tokens: list[str] = []
        alias_to_id: dict = {}
        async for chunk in OllamaConnector.stream_text(
            context=context["generation_context"],
            question=req.content,
            history=history,
        ):
            if isinstance(chunk, dict):
                alias_to_id = chunk
            else:
                raw_tokens.append(chunk)
                await send_token(chunk)
        model_name: str | None = alias_to_id.pop("_model", None)
        response = OllamaConnector._post_process("".join(raw_tokens), alias_to_id)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    logging.info(f"[conversation] answer generated took={int((time.time()-t0)*1000)}ms")

    # If the LLM found no relevant data, still surface the retrieved sources so the
    # user can follow up themselves — append them as citation tokens the frontend renders.
    # Use a normalised check (strip + lower) so minor LLM whitespace/case variations still match.
    _no_data = response.strip().lower().startswith(NO_DATA_RESPONSE.lower())
    if _no_data:
        source_ids = context.get('sources_ids', [])
        if source_ids:
            citations = ' '.join(f'[{sid}]' for sid in source_ids)
            response = f"{response}\n\nRelated sources: {citations}"

    # Record analytics for search
    try:
        from src.db.models import SearchAnalytic
        metrics = context.get('search_metrics', {})
        analytic = SearchAnalytic(
            conversation_id=conversation.id,
            message_id=user_message.id,
            search_query=req.content[:500],
            result_count=metrics.get('result_count', 0),
            top_score=metrics.get('top_score'),
            avg_score=metrics.get('avg_score'),
            min_score=metrics.get('min_score'),
            sufficient_evidence=0 if _no_data else 1,
            fallback_triggered=0,
        )
        db.add(analytic)
        db.commit()
    except Exception:
        logging.exception("[analytics] failed to record")
        db.rollback()
    await emit('saving_assistant_message', {})

    try:
        assistant_message = add_message(
            db=db,
            conversation_id=conversation.id,
            role="assistant",
            content=response,
            sources_ids=context.get('sources_ids'),
            model_name=model_name,
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
    limit: int = Query(10, ge=1, le=100),
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
    if not _check_message_rate(str(current_user.id)):
        raise HTTPException(status_code=429, detail="Too many messages. Please wait before sending another.")
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
    uid = str(current_user.id)
    if _active_ws[uid] >= _WS_MAX_PER_USER:
        await websocket.close(code=1008)
        return
    _active_ws[uid] += 1
    await websocket.accept()

    async def emit(stage: str, data: Dict[str, Any] | None = None) -> None:
        await websocket.send_json({
            'type': 'stage',
            'stage': stage,
            'data': data or {},
        })

    async def send_token(token: str) -> None:
        await websocket.send_json({'type': 'token', 'token': token})

    try:
        if not _check_message_rate(uid):
            await websocket.send_json({'type': 'error', 'message': 'Too many messages. Please wait before sending another.'})
            await websocket.close(code=1008)
            return

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
            send_token=send_token,
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
    finally:
        _active_ws[uid] = max(0, _active_ws[uid] - 1)

class CreateConversationRequest(BaseModel):
    title: str = ""

@router.post("/create/", status_code=201)
async def create_empty_conversation(
    req: CreateConversationRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    title = req.title.strip()[:50] or "New Conversation"
    conversation = create_conversation(db=db, user_id=current_user.id, title=title)
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "lastMessage": None,
        "lastMessageTime": None,
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