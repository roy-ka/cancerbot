from __future__ import annotations

from datetime import datetime, timezone
from typing import  List, Optional
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, JSON, Float, Boolean, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, relationship, mapped_column
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
    last_login = Column(DateTime(timezone=True), nullable=True, default=None)

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
    deleted_at = Column(DateTime(timezone=True), nullable=True, default=None)

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

    _sources: Optional[List[dict]] = None

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

    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages",
        passive_deletes=True,
    )
    

class FallbackSearch(Base):
    """Tracks questions that triggered a fallback search (PubMed / CrossRef / Wikipedia)."""
    __tablename__ = "fallback_searches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    question = Column(Text, nullable=False)
    terms = Column(JSON, nullable=True)           # list[str] — NLP-extracted search terms
    initial_sources = Column(JSON, nullable=True) # list[{id, title, score, source_type, index}]
    pubmed_found = Column(Float, nullable=True)
    crossref_found = Column(Float, nullable=True)
    wikipedia_found = Column(Float, nullable=True)
    indexed = Column(Float, nullable=True)
    searched_web = Column(Boolean, nullable=False, default=False)  # True when fallback triggered a net search
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class Abbreviation(Base):
    __tablename__ = "abbreviations"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    short: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )

    long: Mapped[str] = mapped_column(String, nullable=False)

    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="manual",
    )

    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )