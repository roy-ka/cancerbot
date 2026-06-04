from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import Literal, Optional
import json
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


@router.websocket("/{conversation_id}/add_message/ws")
async def websocket_add_message(websocket: WebSocket, conversation_id: UUID):
    """WebSocket endpoint for real-time message generation with status updates."""
    await websocket.accept()
    logging.info(f"[websocket] Connected for conversation {conversation_id}")

    try:
        # Receive the message
        data = await websocket.receive_text()
        req = Message(**json.loads(data))
        logging.debug(f"[websocket] Received message: {req.content}")

        # Get database session (need to create it manually for WebSocket)
        from src.deps.db import SessionLocal
        db = SessionLocal()

        try:
            # Get current user from token (WebSocket auth)
            from src.auth.security import SecurityUtils
            from jose import JWTError
            from src.db.repositories.users import get_user_by_id

            token = None
            auth_header = websocket.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header.split(" ", 1)[1].strip()
            else:
                # Try to get from query params (common in WebSocket)
                token = websocket.query_params.get("token")

            if not token:
                await websocket.send_json({"status": "error", "detail": "No authentication token"})
                await websocket.close(code=1008)
                return

            try:
                payload = SecurityUtils.decode_jwt_token(token)
                user_id = payload.get("sub")
                if not user_id:
                    raise JWTError("Invalid token payload")
                current_user = get_user_by_id(db=db, user_id=user_id)
                if not current_user:
                    raise JWTError("User not found")
            except JWTError as e:
                logging.warning(f"[websocket] Auth failed: {e}")
                await websocket.send_json({"status": "error", "detail": "Unauthorized"})
                await websocket.close(code=1008)
                return

            if not current_user:
                await websocket.send_json({"status": "error", "detail": "Unauthorized"})
                await websocket.close(code=1008)
                return

            # Get conversation
            conversation = get_conversation_by_id_no_auth(db=db, conversation_id=conversation_id)
            if not conversation or str(conversation.user_id) != str(current_user.id):
                await websocket.send_json({"status": "error", "detail": "Conversation not found"})
                await websocket.close(code=1008)
                return

            # Send loading status
            await websocket.send_json({"status": "loading"})

            # Save user message
            await websocket.send_json({"status": "saving_user_message"})
            user_message = add_message(
                db=db,
                conversation_id=conversation.id,
                role="user",
                content=req.content,
            )
            db.commit()
            db.refresh(user_message)
            logging.debug(f"[websocket] User message saved: {user_message.id}")

            # Retrieval
            await websocket.send_json({"status": "retrieving_context"})
            logging.debug(f"[websocket] Running retrieval...")
            context = run_retrieval(req.content)

            # Generation
            await websocket.send_json({"status": "generating_answer"})
            logging.debug(f"[websocket] Generating answer with {len(context.get('generation_context', []))} context items...")
            response = OllamaConnector.generate_text(
                context=context["generation_context"],
                question=req.content,
                conversation=conversation,
            )

            # Save assistant message
            sources_ids = context.get('sources_ids')
            assistant_message = add_message(
                db=db,
                conversation_id=conversation.id,
                role="assistant",
                content=response,
                intent=context.get("intent"),
                claim_ids=context.get('claims_ids'),
                sources_ids=sources_ids
            )
            db.commit()
            db.refresh(assistant_message)
            logging.debug(f"[websocket] Assistant message saved: {assistant_message.id}")

            # Send complete message
            await websocket.send_json({
                "status": "done",
                "messages": [
                    {
                        "id": str(user_message.id),
                        "role": "user",
                        "content": user_message.content,
                        "sources": [],
                        "claims": [],
                    },
                    {
                        "id": str(assistant_message.id),
                        "role": "assistant",
                        "content": assistant_message.content,
                        "sources": sources_ids or [],
                        "claims": context.get('claims_ids') or [],
                    }
                ],
                "conversation": {
                    "id": str(conversation.id),
                    "title": conversation.title,
                    "updatedAt": assistant_message.created_at.isoformat(),
                    "lastMessage": user_message.content,
                    "lastMessageTime": format_last_msg_time(user_message.created_at),
                }
            })

        finally:
            db.close()

    except WebSocketDisconnect:
        logging.info(f"[websocket] Client disconnected from conversation {conversation_id}")
    except Exception as e:
        logging.exception(f"[websocket] Error in conversation {conversation_id}: {e}")
        try:
            await websocket.send_json({"status": "error", "detail": str(e)})
        except Exception:
            pass
        await websocket.close(code=1011)


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