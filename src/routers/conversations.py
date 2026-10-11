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
    set_use_profile_context,
    enable_share,
    disable_share,
)
from src.routers.auth import _get_frontend_url
from src.db.repositories.profile import get_profile, render_profile_context, render_profile_recall, PROFILE_FIELDS
from src.db.repositories.messeges import (
    add_message,
    add_claims_and_sources,
    append_to_message,
    get_messages_by_conversation_id,
    get_recent_messages,
    get_message_by_id,
    get_messages_up_to,
    copy_messages,
    get_message_texts_for_summary,
)
from src.db.repositories.message_feedback import set_feedback, get_feedback_for_messages
from uuid import UUID
from src.retrieval import run_retrieval
from src.retrieval.db_connector import dbConnector
from src.classes.ollama_connector import OllamaConnector, NO_DATA_RESPONSE, is_truncated_finish_reason
from src.routers.conversation_helper import _emit_noop, search_and_embed, fetch_url_contents, _representative_terms
from src.utils.timing import timed_stage

ROLLS = Literal['user', 'assistant']

_user_msg_times: dict[str, list[float]] = defaultdict(list)
_MSG_RATE_WINDOW = 60.0
_MSG_RATE_MAX = 10
# How often expired entries are swept out of _user_msg_times. Without this the
# dict keeps one key per user id that has ever sent a message, for the life of
# the process.
_RATE_SWEEP_INTERVAL = 300.0
_last_rate_sweep = 0.0


def _sweep_message_rates(now: float) -> None:
    """Drop users whose rate-limit window has fully expired."""
    global _last_rate_sweep
    if now - _last_rate_sweep < _RATE_SWEEP_INTERVAL:
        return
    _last_rate_sweep = now
    cutoff = now - _MSG_RATE_WINDOW
    for user_id in [uid for uid, times in _user_msg_times.items() if not any(t > cutoff for t in times)]:
        del _user_msg_times[user_id]


def _check_message_rate(user_id: str) -> bool:
    now = time.monotonic()
    _sweep_message_rates(now)
    cutoff = now - _MSG_RATE_WINDOW
    times = _user_msg_times[user_id]
    times[:] = [t for t in times if t > cutoff]
    if len(times) >= _MSG_RATE_MAX:
        return False
    times.append(now)
    return True

# NOTE: both of these live in process memory, so with more than one uvicorn
# worker each worker enforces its own budget and the effective limit is
# multiplied by the worker count. Move them to Postgres/Redis before scaling out.
_active_ws: dict[str, int] = defaultdict(int)
_WS_MAX_PER_USER = 3

# Outer safety net around the generate_answer stage. The Groq/Gemini clients
# (ollama_connector.py) already carry their own network-level timeouts that
# trigger the Groq->Gemini fallback; this catches anything that slips past
# that — so a message can never hang the websocket forever with zero
# logging and zero client-visible error, the way the 2026-09-16 incident did
# (traced via Axiom: search_and_embed and one retrieval query completed,
# then total silence — no timing log, no exception, no WS frame, because
# nothing was ever raised for anything to catch).
_GENERATE_ANSWER_TIMEOUT_SECONDS = 120.0

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


def _allowed_ws_origins() -> set[str]:
    """Origins permitted to open a WebSocket, from the same list CORS uses."""
    raw = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    return {origin.strip().rstrip('/') for origin in raw.split(",") if origin.strip()}


def _is_allowed_ws_origin(origin: str | None) -> bool:
    """Whether a handshake carrying this Origin header may proceed.

    A missing Origin is allowed: browsers always send one on a WebSocket
    handshake, so its absence means a non-browser client (tests, scripts, a
    native app), which is not subject to the cross-site attack this guards
    against and has no cookie to abuse in the first place.
    """
    if origin is None:
        return True
    allowed = _allowed_ws_origins()
    if "*" in allowed:
        return True
    return origin.strip().rstrip('/') in allowed


router = APIRouter(prefix="/conversations", tags=["conversations"])


def _msg_to_dict(m):
    return {
        "id": str(m.id),
        "role": m.role,
        "content": m.content,
        "created_at": m.created_at.isoformat() if getattr(m, 'created_at', None) else None,
        "sources": getattr(m, 'sources', None),
        "truncated": getattr(m, 'truncated', False),
    }


async def _answer_via_retrieval(
    *,
    conversation,
    conversation_id: UUID,
    req: Message,
    db: Session,
    user_message,
    hidden_from_user: bool,
    is_first_message: bool,
    profile_context: str | None,
    emit: StageEmitter,
    send_token: SendToken,
    t0: float,
) -> tuple[str, str | None, bool, dict]:
    """The literature-search-and-generate pipeline: search_and_embed ->
    retrieve_context -> build_prompt/generate_answer. Split out of
    _process_post_message (body unchanged, just relocated) so the
    personal-question fast path there can skip this whole thing — a
    profile-data recall must never share a generation call with a
    citation-grounded literature answer. Returns (response, model_name,
    truncated, context) for the caller's shared save/title/done tail."""
    await emit('fallback_triggered', {'reason': 'always_search_external'})
    async with timed_stage('search_and_embed', conversation_id=str(conversation_id)):
        search_meta = await search_and_embed(conversation, emit=emit)

    # Persist the terms extracted for this message. search_and_embed already ran
    # spell-correction + entity extraction on this exact text, so its result is
    # reused here rather than extracting a second time — the NLP service is the
    # most CPU-expensive hop in the request and one pass is enough.
    # `latest_terms` is this message's own terms (what the old separate call
    # produced); the merged `terms` list is the fallback for when NLP came back
    # empty (e.g. a bare abbreviation like "gbm") and word-extraction stood in.
    extracted_terms = search_meta.get('latest_terms') or search_meta.get('terms') or []
    if extracted_terms:
        try:
            user_message.extracted_terms = extracted_terms
            db.add(user_message)
            db.commit()
            logging.info(
                "[conversation] saved extracted_terms=%s to message %s",
                extracted_terms,
                user_message.id,
            )
        except Exception as e:
            logging.warning("[conversation] saving extracted_terms failed: %s: %s", type(e).__name__, e)
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

            for source_type in ['pubmed', 'crossref', 'wikipedia', 'clinicaltrials']:
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
    # For a follow-up whose own text names nothing ("what can block these
    # pathways?"), search_and_embed already resolved it against recent
    # history before extraction ran — rewritten_query is that resolved text,
    # same as req.content when there was nothing to resolve. Falling back to
    # this instead of req.content keeps the KNN query (and the terms/BM25
    # fallback below) from reverting to the unresolved pronoun-laden message.
    rewritten_query = (search_meta.get('rewritten_query') or '').strip() or req.content
    retrieval_terms = _representative_terms(entity_groups, extracted_query_terms)
    retrieval_query = ' '.join(retrieval_terms) if retrieval_terms else rewritten_query
    if url_context_items:
        first_title = (url_context_items[0].get('title') or '').strip()
        if first_title and first_title != req.content:
            retrieval_query = first_title

    # The dense (KNN) half searches on the natural question instead of the
    # joined terms: the terms exist to fix BM25/keyword-API behaviour, while
    # the embedding model is trained on sentences. Rank fusion keeps the two
    # halves independent, so they can describe the query differently. The
    # exception is a message that was just a URL — there the fetched page
    # title is the only meaningful thing to embed.
    dense_query = retrieval_query if url_context_items else (rewritten_query or retrieval_query)

    # Disease areas of the query's own entities (e.g. "brain cancer" for GBM)
    # let retrieval boost sources tagged with the same area.
    query_disease_areas = sorted({
        (g.get('category') or '').strip().lower()
        for g in entity_groups
        if (g.get('category') or '').strip()
    })

    async with timed_stage('retrieve_context', conversation_id=str(conversation_id)):
        context = await asyncio.to_thread(
            run_retrieval, retrieval_query, query_disease_areas, dense_query
        )
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
    # Ninja's own turn sees the full thread (real history + any earlier hidden
    # ninja exchanges) for continuity; a real user's turn never includes
    # hidden messages in its prompt context.
    history = get_recent_messages(db, conversation.id, limit=max_history, include_hidden=hidden_from_user)

    # The answer should be in whatever language the conversation actually
    # started in — not just the current message's language, which can drift
    # over a long conversation. conversation.messages is the full (unlimited)
    # relationship, unlike `history` above which is capped at max_history, so
    # this stays correct even once the true first message has scrolled out of
    # the prompt window. Ninja's own hidden messages are skipped so ninja
    # typing in another language for a QA check can't change the language the
    # real user gets answered in.
    if is_first_message:
        first_message_content = req.content
    else:
        first_message_content = next(
            (m.content for m in conversation.messages if m.role == 'user' and not m.hidden_from_user),
            req.content,
        )

    await emit('building_prompt', {'history_messages': len(history)})
    await emit('generating_answer', {})

    raw_tokens: list[str] = []
    alias_to_id: dict = {}

    async def _run_generation() -> None:
        nonlocal alias_to_id
        async for chunk in OllamaConnector.stream_text(
            context=context["generation_context"],
            question=req.content,
            history=history,
            first_message=first_message_content,
            profile_context=profile_context,
        ):
            if isinstance(chunk, dict):
                alias_to_id = chunk
            else:
                raw_tokens.append(chunk)
                await send_token(chunk)

    try:
        async with timed_stage('generate_answer', conversation_id=str(conversation_id)):
            await asyncio.wait_for(_run_generation(), timeout=_GENERATE_ANSWER_TIMEOUT_SECONDS)
        model_name: str | None = alias_to_id.pop("_model", None)
        truncated = is_truncated_finish_reason(alias_to_id.pop("_finish_reason", None))
        response = OllamaConnector._post_process("".join(raw_tokens), alias_to_id)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except asyncio.TimeoutError:
        logging.error(
            "[conversation] generate_answer timed out after %ss conversation_id=%s",
            _GENERATE_ANSWER_TIMEOUT_SECONDS, conversation_id,
        )
        raise HTTPException(status_code=504, detail="Answer generation timed out. Please try again.")
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

    return response, model_name, truncated, context


async def _process_post_message(
    *,
    conversation_id: UUID,
    req: Message,
    db: Session,
    current_user,
    conversation=None,
    emit: StageEmitter = _emit_stage_noop,
    send_token: SendToken = _send_token_noop,
    hidden_from_user: bool = False,
):
    t0 = time.time()

    logging.info(f"[conversation] msg conversation_id={conversation_id} user={current_user.id}")

    await emit('loading_conversation', {'conversation_id': str(conversation_id)})

    if conversation is None:
        async with timed_stage('load_conversation', conversation_id=str(conversation_id)):
            conversation = get_conversation_by_id_no_auth(
                db=db,
                conversation_id=conversation_id,
            )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        # Ninja intentionally posts into other users' conversations — the
        # hidden_from_user flag is only ever set by the ninja-only router,
        # which has already authorized the caller via get_current_ninja_user.
        if not hidden_from_user and str(conversation.user_id) != str(current_user.id):
            raise HTTPException(status_code=403, detail="Forbidden")

    # Capture before adding this message — used later to decide whether to
    # auto-generate a title. A hidden ninja message never counts as "first"
    # (and never triggers title generation), so ninja activity can't change
    # what the real user sees in their conversation list.
    is_first_message = not hidden_from_user and len(conversation.messages) == 0

    await emit('saving_user_message', {})

    try:
        async with timed_stage('save_user_message', conversation_id=str(conversation_id)):
            user_message = add_message(
                db=db,
                conversation_id=conversation.id,
                role="user",
                content=req.content,
                urls=req.urls,
                hidden_from_user=hidden_from_user,
            )
            db.commit()
            db.refresh(user_message)
            db.refresh(conversation)
    except Exception:
        db.rollback()
        raise

    # Personal-question fast path: only worth the extra classification call
    # when there's a populated profile that could actually answer something
    # (ninja's own turn never gets this — a debugging tool with no profile
    # row of its own, same reasoning _answer_via_retrieval's profile_context
    # already followed). A factual recall of saved profile data is kept
    # entirely separate from the literature-search/generation pipeline —
    # see render_profile_recall and OllamaConnector.classify_personal_question
    # — since blending "what you told us" into the same generation call as a
    # cited medical answer is exactly the ambiguity that must not happen.
    profile = None
    personal_recall_text: str | None = None
    skip_literature_search = False
    if not hidden_from_user and conversation.use_profile_context:
        profile = get_profile(db, current_user.id)
        if profile and any(getattr(profile, f) for f in PROFILE_FIELDS):
            async with timed_stage('classify_personal_question', conversation_id=str(conversation_id)):
                classification = await OllamaConnector.classify_personal_question(req.content)
            personal_fields = classification.get('personal_fields', [])
            has_untracked_personal_ask = classification.get('has_untracked_personal_ask', False)
            has_general_question = classification.get('has_general_question', True)
            if personal_fields or has_untracked_personal_ask:
                personal_recall_text = render_profile_recall(profile, personal_fields, has_untracked_personal_ask)
                skip_literature_search = not has_general_question

    profile_context = render_profile_context(profile) if profile else None

    if skip_literature_search:
        await emit('answering_from_profile', {})
        response = personal_recall_text
        model_name = None
        truncated = False
        context = {'sources_ids': []}
    else:
        response, model_name, truncated, context = await _answer_via_retrieval(
            conversation=conversation,
            conversation_id=conversation_id,
            req=req,
            db=db,
            user_message=user_message,
            hidden_from_user=hidden_from_user,
            is_first_message=is_first_message,
            profile_context=profile_context,
            emit=emit,
            send_token=send_token,
            t0=t0,
        )
        if personal_recall_text:
            response = f"{personal_recall_text}\n\n{response}"

    await emit('saving_assistant_message', {})

    try:
        async with timed_stage('save_assistant_message', conversation_id=str(conversation_id)):
            assistant_message = add_message(
                db=db,
                conversation_id=conversation.id,
                role="assistant",
                content=response,
                sources_ids=context.get('sources_ids'),
                model_name=model_name,
                hidden_from_user=hidden_from_user,
                truncated=truncated,
            )

            db.commit()
            db.refresh(assistant_message)
    except Exception:
        db.rollback()
        raise

    add_claims_and_sources(assistant_message)

    # Auto-generate the conversation title now that the answer is fully
    # generated and saved — the streamed text itself was never delayed by
    # this, only the trailing 'done'/'final' signal is.
    if is_first_message:
        try:
            async with timed_stage('generate_title', conversation_id=str(conversation_id)):
                new_title = await OllamaConnector.generate_title(req.content)
                conversation.title = new_title
                db.add(conversation)
                db.commit()
        except Exception:
            logging.exception("[conversation] title generation failed")
            db.rollback()

    took_ms = int((time.time() - t0) * 1000)
    logging.info(
        "[timing] stage=total_message took_ms=%dms", took_ms,
        extra={"stage": "total_message", "took_ms": took_ms, "conversation_id": str(conversation_id)},
    )
    await emit('done', {'took_ms': took_ms})

    return {
        "messages": [_msg_to_dict(user_message), _msg_to_dict(assistant_message)],
        "conversation": {
            "id": str(conversation.id),
            "title": conversation.title,
            "updatedAt": assistant_message.created_at.isoformat() if getattr(assistant_message, 'created_at', None) else None,
            "lastMessage": user_message.content,
            "lastMessageTime": format_last_msg_time(user_message.created_at),
            "use_profile_context": conversation.use_profile_context,
        },
    }


async def _process_continue_message(
    *,
    message_id: UUID,
    db: Session,
    current_user,
    emit: StageEmitter = _emit_stage_noop,
    send_token: SendToken = _send_token_noop,
):
    """Extend a message previously cut short by GROQ_MAX_TOKENS, reusing the
    same evidence sources rather than re-running retrieval — see
    OllamaConnector.stream_continuation."""
    t0 = time.time()

    message = get_message_by_id(db, message_id)
    if message is None or message.role != 'assistant':
        raise HTTPException(status_code=404, detail="Message not found")
    if not message.truncated:
        raise HTTPException(status_code=400, detail="Message was not truncated")

    conversation = get_conversation_by_id_no_auth(db=db, conversation_id=message.conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if str(conversation.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    original_question = next(
        (
            m.content for m in sorted(conversation.messages, key=lambda m: m.created_at, reverse=True)
            if m.role == 'user' and m.created_at <= message.created_at
        ),
        "",
    )
    first_message_content = next(
        (m.content for m in conversation.messages if m.role == 'user' and not m.hidden_from_user),
        original_question,
    )

    add_claims_and_sources(message)

    await emit('generating_answer', {})

    raw_tokens: list[str] = []
    finish_reason: str | None = None
    model_name: str | None = None

    async def _run_continuation() -> None:
        nonlocal finish_reason, model_name
        async for chunk in OllamaConnector.stream_continuation(
            sources=getattr(message, 'sources', None) or [],
            original_question=original_question,
            prior_answer=message.content,
            first_message=first_message_content,
        ):
            if isinstance(chunk, dict):
                model_name = chunk.get("_model") or model_name
                finish_reason = chunk.get("_finish_reason")
            else:
                raw_tokens.append(chunk)
                await send_token(chunk)

    try:
        # Same outer deadline as the fresh-answer path (_process_post_message)
        # — see _GENERATE_ANSWER_TIMEOUT_SECONDS for why this exists.
        await asyncio.wait_for(_run_continuation(), timeout=_GENERATE_ANSWER_TIMEOUT_SECONDS)
        extra_content = "".join(raw_tokens)
        truncated = is_truncated_finish_reason(finish_reason)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except asyncio.TimeoutError:
        logging.error(
            "[conversation] generate_answer (continue) timed out after %ss message_id=%s",
            _GENERATE_ANSWER_TIMEOUT_SECONDS, message_id,
        )
        raise HTTPException(status_code=504, detail="Answer generation timed out. Please try again.")

    message = append_to_message(db, message, extra_content, truncated)
    if model_name:
        message.model_name = model_name
        db.commit()
        db.refresh(message)

    add_claims_and_sources(message)

    took_ms = int((time.time() - t0) * 1000)
    await emit('done', {'took_ms': took_ms})

    return {"continued_message": _msg_to_dict(message)}


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

    # Authorize before doing any work. get_conversation_by_id already filters on
    # user_id, so a conversation belonging to someone else is indistinguishable
    # from one that doesn't exist. Loading the page first meant an arbitrary
    # conversation id cost a message query plus an OpenSearch source lookup
    # before being rejected.
    if conversation is None:
        logging.error("couldn't find conversation id: %s", conversation_id)
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Redundant given the filter above, kept as defence in depth
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

    feedback_by_message = get_feedback_for_messages(
        db=db,
        message_ids=[msg.id for msg in messages],
        user_id=current_user.id,
    )

    messages_data = [
        {
            "id": str(msg.id),
            "role": msg.role,
            "content": msg.content,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "sources": msg.sources,
            "feedback": feedback_by_message.get(str(msg.id)),
            "truncated": msg.truncated,
        }
        for msg in messages
    ]

    return {
        "conversation": {
            "id": str(conversation.id),
            "title": conversation.title,
            "updatedAt": conversation.updated_at.isoformat() if conversation.updated_at else None,
            "use_profile_context": conversation.use_profile_context,
            "shared": bool(conversation.share_token),
        },
        "messages": messages_data,
        "next_before": next_before,
    }

@router.post("/{conversation_id}/summarize")
async def summarize_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    conversation = get_conversation_by_id(
        db=db,
        conversation_id=conversation_id,
        current_user=current_user,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    pairs = get_message_texts_for_summary(db, conversation_id)
    if not pairs:
        raise HTTPException(status_code=422, detail="Conversation has no messages to summarize")

    transcript = "\n\n".join(
        f"{'User' if role == 'user' else 'CancerBot'}: {content}" for role, content in pairs
    )

    try:
        summary = await OllamaConnector.summarize_conversation(transcript)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if not summary:
        raise HTTPException(status_code=502, detail="Failed to generate a summary")

    return {"summary": summary}


class FeedbackRequest(BaseModel):
    vote: Literal[1, -1]


@router.post("/{conversation_id}/messages/{message_id}/feedback")
async def submit_message_feedback(
    conversation_id: UUID,
    message_id: UUID,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    conversation = get_conversation_by_id(db=db, conversation_id=conversation_id, current_user=current_user)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    message = get_message_by_id(db=db, message_id=message_id)
    if message is None or str(message.conversation_id) != str(conversation_id):
        raise HTTPException(status_code=404, detail="Message not found")
    if message.role != "assistant":
        raise HTTPException(status_code=400, detail="Feedback is only supported on assistant messages")

    vote = set_feedback(db=db, message_id=message_id, user_id=current_user.id, vote=req.vote)
    return {"vote": vote}


@router.post("/{conversation_id}/messages/{message_id}/split", status_code=201)
async def split_conversation(
    conversation_id: UUID,
    message_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    conversation = get_conversation_by_id(db=db, conversation_id=conversation_id, current_user=current_user)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    message = get_message_by_id(db=db, message_id=message_id)
    if message is None or str(message.conversation_id) != str(conversation_id):
        raise HTTPException(status_code=404, detail="Message not found")
    if message.role != "assistant":
        raise HTTPException(status_code=400, detail="You can only split at an assistant message")

    source_messages = get_messages_up_to(db=db, conversation_id=conversation_id, message_id=message_id)
    if not source_messages:
        raise HTTPException(status_code=404, detail="Message not found")

    # Title the new conversation from the question that led to this answer,
    # not the answer itself — generate_title expects "the message a
    # conversation starts with", and a short question makes a far better
    # title than a long generated answer.
    preceding_user_message = next(
        (m for m in reversed(source_messages) if m.role == "user"), None
    )
    title_source = preceding_user_message.content if preceding_user_message else message.content
    title = await OllamaConnector.generate_title(title_source)

    new_conversation = create_conversation(
        db=db,
        user_id=current_user.id,
        title=title,
        forked_from_conversation_id=conversation_id,
        forked_from_message_id=message_id,
    )
    copy_messages(db=db, messages=source_messages, dest_conversation_id=new_conversation.id)

    return {
        "id": str(new_conversation.id),
        "title": new_conversation.title,
        "lastMessage": None,
        "lastMessageTime": None,
    }


@router.post("/{conversation_id}/add_message")
async def post_message(
    conversation_id: UUID,
    req: Message,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    if not _check_message_rate(str(current_user.id)):
        raise HTTPException(status_code=429, detail="Too many messages. Please wait before sending another.")
    return await _process_post_message(
        conversation_id=conversation_id,
        req=req,
        db=db,
        current_user=current_user,
    )


@router.websocket('/{conversation_id}/add_message/ws')
async def post_message_ws(
    websocket: WebSocket,
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # CORSMiddleware does not apply to WebSocket handshakes, so the Origin
    # check has to happen here. A cross-site page opening a socket with the
    # victim's cookie is largely blocked by SameSite=Lax already; this closes
    # the remaining gap (non-conforming or older clients) rather than relying
    # on cookie policy alone.
    if not _is_allowed_ws_origin(websocket.headers.get("origin")):
        logging.warning(
            "[ws] rejected handshake from disallowed origin: %r",
            websocket.headers.get("origin"),
        )
        await websocket.close(code=1008)
        return

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

        await emit('received', {'conversation_id': str(conversation_id)})

        continue_message_id = payload.get('continue_message_id')
        if continue_message_id:
            result = await _process_continue_message(
                message_id=UUID(continue_message_id),
                db=db,
                current_user=current_user,
                emit=emit,
                send_token=send_token,
            )
        else:
            req = Message(**payload)
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
        remaining = max(0, _active_ws[uid] - 1)
        if remaining:
            _active_ws[uid] = remaining
        else:
            # Drop the key entirely rather than leaving a 0 behind, so the dict
            # doesn't accumulate one entry per user that ever opened a socket.
            _active_ws.pop(uid, None)

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
        "use_profile_context": conversation.use_profile_context,
    }


@router.post("/new")
async def new_conversation(
    req: Message,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    if not _check_message_rate(str(current_user.id)):
        raise HTTPException(status_code=429, detail="Too many messages. Please wait before sending another.")
    conversation = create_conversation(db=db, user_id=current_user.id, title=req.content[:20])
    return await _process_post_message(
        conversation_id=conversation.id,
        req=req,
        db=db,
        current_user=current_user,
        conversation=conversation,
    )


class UpdateConversationRequest(BaseModel):
    use_profile_context: bool


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: UUID,
    req: UpdateConversationRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    conversation = set_use_profile_context(
        db=db, conversation_id=conversation_id, user_id=current_user.id,
        use_profile_context=req.use_profile_context,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"id": str(conversation.id), "use_profile_context": conversation.use_profile_context}


@router.post("/{conversation_id}/share")
async def share_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    token = enable_share(db=db, conversation_id=conversation_id, user_id=current_user.id)
    if token is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # /s/ (not /shared/) on purpose — /shared/ is the backend API prefix
    # (see nginx.conf), and nginx routes that whole prefix straight to the
    # backend, so a frontend page living there would never actually render.
    return {"share_token": token, "share_url": f"{_get_frontend_url()}/s/{token}"}


@router.delete("/{conversation_id}/share")
async def unshare_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    success = disable_share(db=db, conversation_id=conversation_id, user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True}


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