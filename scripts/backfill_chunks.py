#!/usr/bin/env python3
"""
One-time migration: backfill existing OpenSearch source docs to the new chunked schema.

For each source referenced by an assistant message:
  1. Tags it with the extracted_terms from the preceding user message (union across all messages)
  2. Splits the content into 150-word chunks with 40-word overlap
  3. Indexes the chunks under new IDs ({source_id}:c0, :c1, …)
  4. Deletes the original single-doc entry

Safe to re-run: already-migrated docs (those that have a source_id field) are skipped.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from src.db.session import SessionLocal
from src.db.models import Message
from src.retrieval.db_connector import dbConnector
from src.classes.ollama_connector import OllamaConnector
from src.routers.conversation_helper import _chunk_text


def _fetch_doc(source_id: str) -> dict | None:
    """Fetch a single old-style doc from OpenSearch by its id field."""
    res = dbConnector.get_sources_by_id([source_id])
    for hit in res.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        if src.get("id") == source_id:
            return src
    return None


def _is_old_doc(doc: dict) -> bool:
    """Return True if this is a pre-migration single doc (no source_id field)."""
    return "source_id" not in doc


def main() -> None:
    logger.info("Initialising OpenSearch connection…")
    dbConnector._initialize()
    if not dbConnector.db_client:
        logger.error("OpenSearch not available — aborting")
        sys.exit(1)

    # ------------------------------------------------------------------ #
    # Step 1: build source_id → set(terms) from PostgreSQL messages table #
    # ------------------------------------------------------------------ #
    source_terms: dict[str, set[str]] = {}

    with SessionLocal() as session:
        assistant_msgs = (
            session.query(Message)
            .filter(Message.role == "assistant", Message.sources_ids.isnot(None))
            .all()
        )
        logger.info("Found %d assistant messages with sources", len(assistant_msgs))

        for msg in assistant_msgs:
            source_ids = msg.source_ids
            if not source_ids:
                continue

            # Find the immediately preceding user message in the same conversation
            user_msg = (
                session.query(Message)
                .filter(
                    Message.conversation_id == msg.conversation_id,
                    Message.role == "user",
                    Message.created_at < msg.created_at,
                )
                .order_by(Message.created_at.desc())
                .first()
            )

            terms: list[str] = []
            if user_msg and isinstance(user_msg.extracted_terms, list):
                terms = [t.strip() for t in user_msg.extracted_terms if t and t.strip()]

            for sid in source_ids:
                source_terms.setdefault(sid, set()).update(terms)

    logger.info("Collected terms for %d unique source IDs", len(source_terms))

    # ------------------------------------------------------------------ #
    # Step 2: migrate each un-migrated source                             #
    # ------------------------------------------------------------------ #
    migrated = skipped_missing = skipped_already = errors = 0

    for source_id, terms in source_terms.items():
        try:
            doc = _fetch_doc(source_id)

            if doc is None:
                logger.debug("Not found in OpenSearch, skipping: %s", source_id)
                skipped_missing += 1
                continue

            if not _is_old_doc(doc):
                logger.debug("Already migrated, skipping: %s", source_id)
                skipped_already += 1
                continue

            full_text = (doc.get("content_for_embedding") or "").strip()
            if not full_text:
                logger.warning("No content for %s, skipping", source_id)
                skipped_missing += 1
                continue

            chunks = _chunk_text(full_text)
            clean_terms = sorted(terms)

            logger.info(
                "Migrating %s — %d chunk(s), %d term(s)", source_id, len(chunks), len(clean_terms)
            )

            for chunk_index, chunk_text in enumerate(chunks):
                embedding = OllamaConnector.embed_text(chunk_text)
                dbConnector.index_to_db(
                    "sources_index",
                    {
                        "id": f"{source_id}:c{chunk_index}",
                        "source_id": source_id,
                        "chunk_index": chunk_index,
                        "source_type": doc.get("source_type"),
                        "pmid": doc.get("pmid"),
                        "doi": doc.get("doi"),
                        "title": doc.get("title"),
                        "full_text": full_text,
                        "content_for_embedding": chunk_text,
                        "tags": clean_terms,
                        "abstract_source": doc.get("abstract_source"),
                        "url": doc.get("url"),
                        "embedding": embedding,
                    },
                )

            dbConnector.delete_source_by_id(source_id)
            migrated += 1

        except Exception as exc:
            logger.error("Failed to migrate %s: %s", source_id, exc)
            errors += 1

    logger.info(
        "Done — migrated=%d  skipped_missing=%d  skipped_already=%d  errors=%d",
        migrated,
        skipped_missing,
        skipped_already,
        errors,
    )


if __name__ == "__main__":
    main()
