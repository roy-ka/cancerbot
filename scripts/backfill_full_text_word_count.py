#!/usr/bin/env python3
"""
Migration: backfill the `full_text_word_count` field on existing OpenSearch
source docs.

New docs get this field set at index time (see _embed_and_index_sources in
src/routers/conversation_helper.py), and src/retrieval/search.py filters
retrieval to only docs with full_text_word_count >= MIN_FULLTEXT_WORDS. Docs
indexed before that field existed have no value for it, so — unlike a range
filter on a field with a real (if short) value — they'd be silently excluded
from every search regardless of how long full_text actually is.

This scrolls every doc missing the field and sets it via update_by_query with
a Painless script that counts words in full_text. Nothing is deleted or
otherwise modified; a genuinely short source ends up with a low word count
and gets excluded by the retrieval filter exactly as intended, while a long
pre-existing source gets backfilled and stays searchable.

Safe to re-run: the query only matches docs still missing the field.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from src.retrieval.db_connector import dbConnector


def main() -> None:
    logger.info("Initialising OpenSearch connection…")
    dbConnector._initialize()
    client = dbConnector.db_client
    if not client:
        logger.error("OpenSearch not available — aborting")
        sys.exit(1)

    index_name = dbConnector._model["sources_index"]

    logger.info("Backfilling full_text_word_count on '%s'…", index_name)
    resp = client.update_by_query(
        index=index_name,
        body={
            "query": {
                "bool": {"must_not": [{"exists": {"field": "full_text_word_count"}}]}
            },
            "script": {
                "lang": "painless",
                "source": (
                    "String text = ctx._source.full_text;"
                    "if (text == null || text.trim().isEmpty()) {"
                    "  ctx._source.full_text_word_count = 0;"
                    "} else {"
                    "  ctx._source.full_text_word_count = text.trim().splitOnToken(' ').length;"
                    "}"
                ),
            },
        },
        params={"wait_for_completion": "true"},
        request_timeout=3600,
    )

    updated = resp.get("updated", 0)
    total = resp.get("total", 0)
    failures = resp.get("failures", [])
    logger.info("Done — total_matched=%d updated=%d failures=%d", total, updated, len(failures))
    if failures:
        logger.error("Failures (first 5): %s", failures[:5])
        sys.exit(1)


if __name__ == "__main__":
    main()
