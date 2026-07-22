#!/usr/bin/env python3
"""
Migration: backfill real titles onto existing conversations.

Before conversation title auto-generation existed, a new conversation's title
was set once, up front, to a naive truncation of the first user message
(either the frontend's `messageText.slice(0, 20)` sent to POST
/conversations/create/, or `req.content[:20]` on the legacy POST
/conversations/new path) — a title like "What role does th" instead of a
real, LLM-generated one like "Cancer Metabolism and Warburg Effect".

This scans every non-deleted conversation whose title still looks like that
naive prefix (title is empty/"New Conversation", or is a strict prefix of the
conversation's first user message and <=20 chars — the exact shape both old
code paths produced) and regenerates it via OllamaConnector.generate_title,
same as a real first message would get today.

Conversations with no user messages yet are skipped (nothing to derive a
title from). Safe to re-run: a conversation whose title no longer matches the
naive-prefix pattern (because it was already backfilled, or was one of the
rare conversations created with an explicit custom title) is left alone.
"""
import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from src.db.session import SessionLocal
from src.db.models import Conversation, Message
from src.classes.ollama_connector import OllamaConnector

_REQUEST_DELAY_SECONDS = 0.5  # be polite to Groq when backfilling many rows

_NAIVE_TITLE_MAX_LEN = 20


def _looks_naive(title: str | None, first_message_content: str) -> bool:
    title = (title or "").strip()
    if not title or title == "New Conversation":
        return True
    if len(title) > _NAIVE_TITLE_MAX_LEN:
        return False
    return first_message_content.strip().startswith(title)


async def main(limit: int | None, dry_run: bool) -> None:
    db = SessionLocal()
    try:
        conversations = (
            db.query(Conversation)
            .filter(Conversation.deleted_at.is_(None))
            .order_by(Conversation.created_at)
            .all()
        )
        logger.info("Scanning %d conversation(s)…", len(conversations))

        candidates: list[tuple[Conversation, Message]] = []
        for conv in conversations:
            first_message = (
                db.query(Message)
                .filter(Message.conversation_id == conv.id, Message.role == "user")
                .order_by(Message.created_at)
                .first()
            )
            if not first_message or not (first_message.content or "").strip():
                continue
            if _looks_naive(conv.title, first_message.content):
                candidates.append((conv, first_message))

        logger.info("%d conversation(s) need a title backfill", len(candidates))

        if limit:
            candidates = candidates[:limit]

        if dry_run:
            for conv, first_message in candidates:
                logger.info("[dry-run] would regenerate title for conversation=%s current_title=%r", conv.id, conv.title)
            logger.info("Dry run — nothing changed. Re-run without --dry-run to apply.")
            return

        updated = failed = 0
        for conv, first_message in candidates:
            try:
                new_title = await OllamaConnector.generate_title(first_message.content)
                conv.title = new_title
                db.add(conv)
                db.commit()
                logger.info("Updated conversation=%s title=%r", conv.id, new_title)
                updated += 1
            except Exception as e:
                logger.warning("Failed to update conversation=%s: %s: %s", conv.id, type(e).__name__, e)
                db.rollback()
                failed += 1
            await asyncio.sleep(_REQUEST_DELAY_SECONDS)

        logger.info("Done — updated=%d failed=%d", updated, failed)
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N conversations (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be updated without writing to the database")
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.dry_run))
