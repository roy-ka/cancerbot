#!/usr/bin/env python3
"""
Migration: backfill ALL old-format OpenSearch source docs to the new chunked schema.

Scrolls the entire sources index and migrates every document that lacks a
`source_id` field (i.e. was indexed before the chunked schema was introduced).

For each such doc:
  1. Tags it with extracted_terms from PostgreSQL messages that cited it (if any),
     falling back to the doc's existing `tags` field.
  2. Splits content into 150-word chunks with 40-word overlap.
  3. Indexes the chunks under new IDs ({source_id}:c0, :c1, …).
  4. Deletes the original single-doc entry.

Safe to re-run: docs that already have a `source_id` field are skipped by the
scroll query itself.
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
from src.classes.embedding_connector import EmbeddingConnector
from src.routers.conversation_helper import _chunk_text

_SCROLL_TTL = "5m"
_BATCH_SIZE = 100


def _scroll_old_docs(db_client, index_name):
    """Yield all docs without a `source_id` field (old-format) via scroll."""
    scroll_id = None
    try:
        resp = db_client.search(
            index=index_name,
            scroll=_SCROLL_TTL,
            body={
                "size": _BATCH_SIZE,
                "_source": True,
                "query": {
                    "bool": {
                        "must_not": [{"exists": {"field": "source_id"}}]
                    }
                },
            },
        )
        scroll_id = resp.get("_scroll_id")
        hits = resp["hits"]["hits"]
        while hits:
            for hit in hits:
                yield hit
            if not scroll_id:
                break
            resp = db_client.scroll(scroll_id=scroll_id, scroll=_SCROLL_TTL)
            scroll_id = resp.get("_scroll_id")
            hits = resp["hits"]["hits"]
    finally:
        if scroll_id:
            try:
                db_client.clear_scroll(scroll_id=scroll_id)
            except Exception:
                pass


def main() -> None:
    logger.info("Initialising OpenSearch connection…")
    dbConnector._initialize()
    if not dbConnector.db_client:
        logger.error("OpenSearch not available — aborting")
        sys.exit(1)

    index_name = dbConnector._model["sources_index"]

    # ------------------------------------------------------------------ #
    # Step 1: build source_id → set(terms) from PostgreSQL messages table #
    # (used to enrich tags on migrated chunks when available)             #
    # ------------------------------------------------------------------ #
    source_terms: dict[str, set[str]] = {}

    try:
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

        logger.info("Collected terms for %d unique source IDs from messages", len(source_terms))
    except Exception as exc:
        logger.warning("Could not load terms from PostgreSQL (%s) — proceeding without enrichment", exc)

    # ------------------------------------------------------------------ #
    # Step 2: scroll ALL old-format docs and migrate them                 #
    # ------------------------------------------------------------------ #
    migrated = skipped = errors = 0

    for hit in _scroll_old_docs(dbConnector.db_client, index_name):
        doc = hit.get("_source", {})
        source_id = (doc.get("id") or "").strip()

        if not source_id:
            logger.warning("Doc with OpenSearch _id=%s has no 'id' field — skipping", hit.get("_id"))
            skipped += 1
            continue

        full_text = (doc.get("content_for_embedding") or "").strip()
        if not full_text:
            logger.warning("No content for %s — skipping", source_id)
            skipped += 1
            continue

        # Prefer terms from PostgreSQL messages; fall back to the doc's existing tags
        if source_id in source_terms:
            clean_terms = sorted(source_terms[source_id])
        else:
            existing_tags = doc.get("tags") or []
            clean_terms = sorted(set(existing_tags)) if isinstance(existing_tags, list) else []

        chunks = _chunk_text(full_text)
        logger.info("Migrating %s — %d chunk(s), %d term(s)", source_id, len(chunks), len(clean_terms))

        try:
            for chunk_index, chunk_text in enumerate(chunks):
                embedding = EmbeddingConnector.embed_text(chunk_text)
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
        "Done — migrated=%d  skipped=%d  errors=%d",
        migrated,
        skipped,
        errors,
    )


if __name__ == "__main__":
    main()
