from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.deps.db import get_db
from src.db.repositories.conversations import get_conversation_by_share_token
from src.db.repositories.messeges import get_messages_by_conversation_id

router = APIRouter(prefix="/shared", tags=["shared"])

# A shared conversation is rendered as a single static page, not paginated
# like the live chat view — high enough to cover any real conversation
# without an unbounded query.
_MAX_SHARED_MESSAGES = 500


@router.get("/{share_token}")
async def get_shared_conversation(
    share_token: str,
    db: Session = Depends(get_db),
):
    """Public, unauthenticated — anyone with the token can view a read-only
    snapshot of that one conversation. No owner info, no per-user feedback
    (there's no user), and hidden_from_user (ninja) messages are excluded by
    get_messages_by_conversation_id's own default, same as every other
    user-facing read path."""
    conversation = get_conversation_by_share_token(db=db, share_token=share_token)
    if conversation is None:
        raise HTTPException(status_code=404, detail="This share link is invalid or has been revoked")

    messages = get_messages_by_conversation_id(
        db=db,
        conversation_id=conversation.id,
        limit=_MAX_SHARED_MESSAGES,
    )

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
            "title": conversation.title,
        },
        "messages": messages_data,
    }
