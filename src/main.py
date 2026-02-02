import logging
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.classes.ollama_connector import OllamaConnector
from src.db import sql
from src.db.repositories.conversations import (
    get_conversation_by_id,
    get_conversations_list_by_user_id,
)
from src.db.repositories.messeges import add_message, get_messages_by_conversation_id
from src.db.repositories.users import (
    create_user ,
    get_user_by_email,
    get_user_by_id,
)
from src.db.session import get_db
from src.retrieval import run_retrieval
from src.auth.security import SecurityUtils


class RetrieveRequest(BaseModel):
    message: str
    conversation_id: UUID | None = None


class CreateUserRequest(BaseModel):
    user_name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI()

# OAuth2PasswordBearer extracts the token from: Authorization: Bearer <token>
# tokenUrl should match your login route.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login/")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    try:
        payload = SecurityUtils.decode_jwt_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Prefer standard JWT claim: sub
    user_id = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_id(db=db, user_id=user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


@app.post("/chat/")
async def chat(
    req: RetrieveRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not req.conversation_id:
        return {"error": "conversation_id is required", "status_code": 400}

    conversation = get_conversation_by_id(db=db, conversation_id=req.conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Enforce ownership
    if str(conversation.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    # Store user message
    with db.begin():
        add_message(
            db=db,
            conversation_id=conversation.id,
            role="user",
            content=req.message,
        )

    # Retrieval + generation outside DB tx
    context = run_retrieval(req.message)
    response = OllamaConnector.generate_text(
        context=context["generation_context"],
        question=req.message,
    )
    response_text = response + "\n\nSources:\n" + "\n".join(context["generation_context"])

    # Store assistant message
    with db.begin():
        add_message(
            db=db,
            conversation_id=conversation.id,
            role="assistant",
            content=response_text,
        )

    return {"response": response_text, "conversation_id": str(conversation.id)}


@app.get("/health/db")
async def health_db(db: Session = Depends(get_db)):
    stmt = sql.select(sql.text("1"))
    with db.begin():
        result = db.execute(stmt)
        return {"status": "ok", "result": [row[0] for row in result]}


@app.get("/debug/conversations/")
async def debug_conversations(db: Session = Depends(get_db)):
    stmt = sql.text("SELECT COUNT(*) FROM conversations")
    with db.begin():
        count = db.execute(stmt).scalar_one()
    return {"conversations_count": int(count)}


@app.get("/conversations/")
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
                "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
            }
            for conv in conversations
        ]
    }


@app.get("/conversations/{conversation_id}/messages/")
async def get_conversation_messages(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    limit: int = 50,
):
    conversation = get_conversation_by_id(db=db, conversation_id=conversation_id)
    if conversation is None:
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
        }
        for msg in messages
    ]

    return {"conversation_id": str(conversation_id), "messages": messages_data}


@app.post("/auth/register/")
async def register_user(req: CreateUserRequest, db: Session = Depends(get_db)):
    # Optional: check for existing email first to return a clean error
    existing = get_user_by_email(db=db, email=req.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    password_hash = SecurityUtils.hash_password(req.password)
    user = create_user(
        db=db,
        user_name=req.user_name,
        email=req.email,
        password_hash=password_hash ,
    )

    return {"user_id": str(user.id), "user_name": user.name, "email": user.email}


@app.post("/auth/login/")
async def generate_token(req: LoginRequest, db: Session = Depends(get_db)):
    user = get_user_by_email(db=db, email=req.email)
    logging.info(f"Attempting login for user: {user.id if user else 'unknown'} with email: {req.email}")
    if not user or not SecurityUtils.verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Standard JWT: subject in 'sub'
    token = SecurityUtils.create_jwt_token({"sub": str(user.id), "email": user.email})
    return {"access_token": token, "token_type": "bearer"}