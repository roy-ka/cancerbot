from __future__ import annotations

from datetime import datetime, timezone
from typing import  List, Optional
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, JSON, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, relationship
from .base import Base

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(150), nullable=True)
    email = Column(String(320), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    conversations: Mapped[List["Conversation"]] = relationship(
        "Conversation",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Conversation.created_at",
        lazy="selectin",
    )

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="conversations")

    messages: Mapped[List["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.created_at",
        lazy="selectin",
    )

class Message(Base):
    __tablename__ = "messages"
    __allow_unmapped__ = True

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    sources_ids = Column(JSON, nullable=True) 
    claim_ids = Column(JSON, nullable=True)
    intent = Column(String(20), nullable=True)

    # --- Virtual fields (not stored as separate DB columns) ---
    # Stored in DB: sources_ids / claim_ids (JSON)
    # Exposed to client: sources / claims (list[dict])
    #
    # The API layer (routers/services) should attach resolved objects by setting
    # `message.sources = [...]` / `message.claims = [...]` where each item is a dict
    # with whatever fields the UI needs (id, title, url, snippet, score, etc.).

    _sources: Optional[List[dict]] = None
    _claims: Optional[List[dict]] = None

    @property
    def source_ids(self) -> List[str]:
        """Always return source IDs as a list of strings (from sources_ids JSON)."""
        val = self.sources_ids
        if val is None:
            return []
        if isinstance(val, list):
            return [str(x) for x in val]
        if isinstance(val, str):
            return [s.strip() for s in val.split(",") if s.strip()]
        return [str(val)]

    @property
    def claim_id_list(self) -> List[str]:
        """Always return claim IDs as a list of strings (from claim_ids JSON)."""
        val = self.claim_ids
        if val is None:
            return []
        if isinstance(val, list):
            return [str(x) for x in val]
        if isinstance(val, str):
            return [s.strip() for s in val.split(",") if s.strip()]
        return [str(val)]

    @property
    def sources(self) -> List[dict]:
        """Client-facing resolved sources.

        If the API layer didn't attach resolved objects, returns minimal dicts
        containing only the stable `id` so the UI can lazy-load details.
        """
        if isinstance(self._sources, list):
            return self._sources
        return [{"id": sid} for sid in self.source_ids]

    @sources.setter
    def sources(self, value: Optional[List[dict]]) -> None:
        # Accept resolved source objects (dicts). Also keep sources_ids in sync.
        if value is None:
            self._sources = None
            return
        self._sources = value
        try:
            self.sources_ids = [str(item.get("id")) for item in value if item.get("id")]
        except Exception:
            # If value isn't a list of dicts, don't crash model usage
            pass

    @property
    def claims(self) -> List[dict]:
        """Client-facing resolved claims.

        If the API layer didn't attach resolved objects, returns minimal dicts
        containing only the stable `id` so the UI can lazy-load details.
        """
        if isinstance(self._claims, list):
            return self._claims
        return [{"id": cid} for cid in self.claim_id_list]

    @claims.setter
    def claims(self, value: Optional[List[dict]]) -> None:
        # Accept resolved claim objects (dicts). Also keep claim_ids in sync.
        if value is None:
            self._claims = None
            return
        self._claims = value
        try:
            self.claim_ids = [str(item.get("id")) for item in value if item.get("id")]
        except Exception:
            pass

    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages",
        passive_deletes=True,
    )

class PasswordResetCode(Base):
    __tablename__ = "password_reset_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_hash = Column(String(64), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)