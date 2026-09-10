from __future__ import annotations

from datetime import datetime, timezone
from typing import  List, Optional
from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, ForeignKey, String, Text, JSON, Integer, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, relationship
from .base import Base

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class TermsAndConditions(Base):
    __tablename__ = "terms_and_conditions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(Integer, unique=True, nullable=False, index=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    first_name = Column(String(150), nullable=True)
    last_name = Column(String(150), nullable=True)
    email = Column(String(320), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)
    terms_version = Column(Integer, nullable=True)
    token_version = Column(Integer, default=1, nullable=False)
    deletion_scheduled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    @property
    def display_name(self) -> str:
        """Single-string name for greetings/UI. Falls back to 'User' when
        both parts are empty (e.g. rows backfilled from a NULL legacy name)."""
        full = f"{self.first_name or ''} {self.last_name or ''}".strip()
        return full or "User"

    conversations: Mapped[List["Conversation"]] = relationship(
        "Conversation",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Conversation.created_at",
        lazy="selectin",
    )

    # No passive_deletes here (unlike `conversations` above, which can be
    # many rows and defers to the DB's ON DELETE CASCADE to avoid loading
    # them all) — this is at most one row, so letting the ORM actively
    # delete it keeps deletion correct even against a DB that doesn't
    # enforce the FK cascade (e.g. SQLite in tests, which needs an explicit
    # PRAGMA this test suite doesn't set).
    profile: Mapped[Optional["UserProfile"]] = relationship(
        "UserProfile",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
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
    # Lineage for the "split to new conversation" feature — plain indexed UUID
    # columns rather than FKs (same choice as SearchAnalytic's conversation_id/
    # message_id), so a later delete of the source conversation/message never
    # blocks or cascades into deleting the split-off conversation.
    forked_from_conversation_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    forked_from_message_id = Column(UUID(as_uuid=True), nullable=True)
    # Per-conversation opt-out of injecting the user's health profile into the
    # prompt (see UserProfile below) — a user with a stored profile may still
    # want to ask something unrelated without it coloring the answer.
    use_profile_context = Column(Boolean, default=True, nullable=False)
    # Public read-only sharing. Null = not shared. A dedicated random token
    # (not the conversation's own id) so revoking is a plain clear/rotate
    # rather than needing to change the conversation's primary key.
    share_token = Column(String(64), nullable=True, unique=True, index=True)

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
    extracted_terms = Column(JSON, nullable=True)
    urls = Column(JSON, nullable=True)
    model_name = Column(String(100), nullable=True)
    hidden_from_user = Column(Boolean, default=False, nullable=False)
    truncated = Column(Boolean, default=False, nullable=False)

    # --- Virtual fields (not stored as separate DB columns) ---
    # Stored in DB: sources_ids (JSON)
    # Exposed to client: sources (list[dict])
    #
    # The API layer (routers/services) should attach resolved objects by setting
    # `message.sources = [...]` where each item is a dict
    # with whatever fields the UI needs (id, title, url, snippet, score, etc.).

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


class MessageFeedback(Base):
    __tablename__ = "message_feedback"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_message_feedback_message_user"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    vote = Column(Integer, nullable=False)  # +1 (thumbs up) or -1 (thumbs down)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class UserProfile(Base):
    """Optional, user-supplied clinical context (cancer type, stage, ...)
    used to tailor prompt framing — see OllamaConnector._build_prompt's
    profile preamble. Every field is nullable: the row's mere existence is
    what signals "this user has already been offered onboarding" (skipping
    without filling anything still creates an all-null row), independent of
    whether any field is actually populated."""
    __tablename__ = "user_profiles"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    cancer_type = Column(String(255), nullable=True)
    stage = Column(String(255), nullable=True)
    biomarkers = Column(Text, nullable=True)
    # Fixed option sets (enforced by the API layer, not a DB constraint) —
    # free text risks the LLM over-anchoring on odd phrasing, and fixed
    # values are what a future retrieval boost would need anyway.
    age_band = Column(String(50), nullable=True)
    treatment_status = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="profile")


class Token(Base):
    """Unified table for every single-purpose token flow: password reset,
    email verification, account deletion, and waitlist invites — see
    src/db/repositories/tokens.py for the type-specific behavior each of
    those still needs (different TTLs, and password_reset alone allows
    multiple verifies via use_count before consumption).

    Exactly one of user_id / waitlist_entry_id is set, never both: the first
    three types belong to an existing User, while waitlist_invite belongs to
    a WaitlistEntry (issued before that person has an account at all)."""
    __tablename__ = "tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    waitlist_entry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("waitlist_entries.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    token_type = Column(String(32), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    # Whichever address this token will set on the account once confirmed —
    # used by email_change (the new address) and email_revert (the old one
    # again). Null for every other token type.
    target_email = Column(String(320), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    use_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(255), nullable=False, index=True)
    failed_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)


class RateLimitEntry(Base):
    __tablename__ = "rate_limit_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    key = Column(String(320), unique=True, index=True, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    blocked_until = Column(DateTime(timezone=True), nullable=True)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(320), unique=True, index=True, nullable=False)
    # Canonical form of `email` (see src/utils/email_normalize.py) — catches
    # dot/plus-tag variations of an email already on the list. Never used to
    # send mail, only to detect duplicates; unique so a race between two
    # requests for variations of the same email can't both insert.
    normalized_email = Column(String(320), unique=True, index=True, nullable=False)
    name = Column(String(150), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    invited = Column(Boolean, default=False, nullable=False)
    invited_at = Column(DateTime(timezone=True), nullable=True)


class SearchAnalytic(Base):
    __tablename__ = "search_analytics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    message_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    search_query = Column(String(500), nullable=False, index=True)
    result_count = Column(Integer, nullable=False, default=0)
    # Raw retrieval scores, stored unscaled. These are the fused RRF scores from
    # search_sources (~0.01-0.03), NOT 0-100 percentages: they were ints scaled
    # by 100 on the assumption that OpenSearch returned 0-1 scores, which the
    # hybrid query never did. Rows written before this became a float are
    # meaningless (~500-2000) and must be excluded from any analysis.
    top_score = Column(Float, nullable=True)  # Highest fused score in the result set
    avg_score = Column(Float, nullable=True)  # Mean fused score
    min_score = Column(Float, nullable=True)  # Lowest fused score
    sufficient_evidence = Column(Integer, default=0, nullable=False)  # 1 if LLM had enough context, 0 otherwise
    fallback_triggered = Column(Integer, default=0, nullable=False)  # 1 if fallback NLP search was triggered
    notes = Column(Text, nullable=True)  # Any additional notes (e.g., error messages)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class BugReport(Base):
    __tablename__ = "bug_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    how_to_reproduce = Column(Text, nullable=True)
    report_type = Column(String(20), nullable=False, default="bug")  # 'bug' or 'feedback'
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class ExternalSearchResult(Base):
    __tablename__ = "external_search_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    message_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    search_query = Column(String(500), nullable=False, index=True)
    source = Column(String(50), nullable=False, index=True)  # 'pubmed', 'crossref', 'wikipedia'
    extracted_terms = Column(Text, nullable=True)  # The terms extracted by NLP (comma-separated)
    result_count = Column(Integer, nullable=False, default=0)  # Total results returned from API
    indexed_count = Column(Integer, nullable=False, default=0)  # How many were actually indexed
    skipped_count = Column(Integer, nullable=False, default=0)  # How many were skipped
    top_result_title = Column(String(500), nullable=True)  # Title of the best result
    top_result_url = Column(String(500), nullable=True)  # URL of the best result
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class UrlClassificationJob(Base):
    __tablename__ = "url_classification_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    url = Column(Text, nullable=False)
    content_text = Column(Text, nullable=False)
    title = Column(Text, nullable=True)
    # pending → processing → done | failed
    status = Column(String(20), nullable=False, default="pending", index=True)
    cancer_related = Column(Boolean, nullable=True)
    llm_reasoning = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)