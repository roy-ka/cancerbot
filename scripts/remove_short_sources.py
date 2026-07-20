#!/usr/bin/env python3
"""
One-off cleanup: remove sources whose full_text is under MIN_FULLTEXT_WORDS words.

Older CrossRef/Wikipedia indexing fell back to title-only or short-summary
content when no real abstract was available (see conversation_helper.py
_search_crossref_sources / _search_wikipedia_sources), producing sources with
only a handful of words of full_text. Those code paths have since been
tightened to stop creating new ones — this script sweeps out what's already
indexed.

full_text is duplicated across every chunk of a source, so this scrolls the
index, groups hits by source_id, and checks the word count once per source.
Any chunked source under the threshold has ALL of its chunks deleted (not
just one doc) via dbConnector.delete_chunks_by_source_id, so no orphan chunks
are left behind for retrieval's `collapse` on source_id.

Docs indexed before the chunked schema was introduced have no `source_id`
field at all (see backfill_chunks.py) — those are matched by their own `id`
and removed via dbConnector.delete_source_by_id instead.

Defaults to --dry-run. Pass --execute to actually delete.
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from src.retrieval.db_connector import dbConnector
from src.routers.conversation_helper import MIN_FULLTEXT_WORDS

_SCROLL_TTL = "5m"
_BATCH_SIZE = 200


def _scroll_all_docs(db_client, index_name):
    scroll_id = None
    try:
        resp = db_client.search(
            index=index_name,
            scroll=_SCROLL_TTL,
            body={
                "size": _BATCH_SIZE,
                "_source": ["id", "source_id", "full_text"],
                "query": {"match_all": {}},
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


def main(limit: int | None, execute: bool) -> None:
    logger.info("Initialising OpenSearch connection…")
    dbConnector._initialize()
    client = dbConnector.db_client
    if not client:
        logger.error("OpenSearch not available — aborting")
        sys.exit(1)

    index_name = dbConnector._model["sources_index"]

    logger.info("Scanning '%s' for sources with full_text under %d words…", index_name, MIN_FULLTEXT_WORDS)
    # chunked docs: keyed by source_id, deleted via delete_chunks_by_source_id.
    # legacy (pre-chunked-schema) docs: no source_id, keyed by their own id,
    # deleted via delete_source_by_id (exact id match).
    short_chunked: dict[str, int] = {}
    short_legacy: dict[str, int] = {}
    scanned = 0
    for hit in _scroll_all_docs(client, index_name):
        scanned += 1
        source = hit["_source"]
        source_id = source.get("source_id")
        doc_id = source.get("id")
        full_text = (source.get("full_text") or "").strip()
        word_count = len(full_text.split())

        if source_id:
            if source_id in short_chunked:
                continue
            if word_count < MIN_FULLTEXT_WORDS:
                short_chunked[source_id] = word_count
        elif doc_id:
            if word_count < MIN_FULLTEXT_WORDS:
                short_legacy[doc_id] = word_count

    logger.info(
        "Scanned %d doc(s) — %d chunked source(s) and %d legacy doc(s) below threshold",
        scanned, len(short_chunked), len(short_legacy),
    )

    to_delete_chunked = list(short_chunked.items())
    to_delete_legacy = list(short_legacy.items())
    if limit:
        to_delete_chunked = to_delete_chunked[:limit]
        to_delete_legacy = to_delete_legacy[: max(0, limit - len(to_delete_chunked))]

    if not execute:
        for source_id, word_count in to_delete_chunked:
            logger.info("[dry-run] would delete chunked source %s (%d word(s))", source_id, word_count)
        for doc_id, word_count in to_delete_legacy:
            logger.info("[dry-run] would delete legacy doc %s (%d word(s))", doc_id, word_count)
        logger.info("Dry run — nothing deleted. Re-run with --execute to delete.")
        return

    deleted_sources = 0
    deleted_chunks = 0
    for source_id, word_count in to_delete_chunked:
        n = dbConnector.delete_chunks_by_source_id(source_id)
        logger.info("Deleted chunked source %s (%d word(s)) — %d chunk(s) removed", source_id, word_count, n)
        deleted_sources += 1
        deleted_chunks += n
    for doc_id, word_count in to_delete_legacy:
        n = dbConnector.delete_source_by_id(doc_id)
        logger.info("Deleted legacy doc %s (%d word(s)) — %d doc(s) removed", doc_id, word_count, n)
        deleted_sources += 1
        deleted_chunks += n

    logger.info("Done — sources_deleted=%d docs_deleted=%d", deleted_sources, deleted_chunks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N short sources (for testing)")
    parser.add_argument("--execute", action="store_true", help="Actually delete. Without this flag, only reports what would be deleted.")
    args = parser.parse_args()
    main(args.limit, args.execute)
