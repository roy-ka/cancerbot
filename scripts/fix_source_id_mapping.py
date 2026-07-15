#!/usr/bin/env python3
"""
One-time migration: fix source_id field mapping from text to keyword.

OpenSearch does not allow changing a field type in place. This script:
  1. Creates a new index with the correct mapping (source_id as keyword)
  2. Reindexes all docs from old → new using a Painless script that
     populates source_id on old-format docs that don't have it
     (derived from the id field by stripping the :cN chunk suffix)
  3. Deletes the old index
  4. Creates an alias with the original index name pointing to the new index

No re-embedding required — all existing embeddings are preserved.
Safe to re-run: exits early if the alias already exists (migration already done).
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

    old_index = dbConnector._model["sources_index"]
    new_index = f"{old_index}_remapped"

    # Idempotency check — if old_index is already an alias the migration is done
    if client.indices.exists_alias(name=old_index):
        logger.info("Alias '%s' already exists — mapping already fixed, nothing to do", old_index)
        sys.exit(0)

    if not client.indices.exists(index=old_index):
        logger.error("Source index '%s' does not exist — aborting", old_index)
        sys.exit(1)

    # ------------------------------------------------------------------ #
    # Step 1: create new index with correct mapping                       #
    # ------------------------------------------------------------------ #
    if client.indices.exists(index=new_index):
        logger.warning("Temp index '%s' already exists — deleting it first", new_index)
        client.indices.delete(index=new_index)

    logger.info("Creating '%s' with correct mapping…", new_index)
    client.indices.create(
        index=new_index,
        body={
            "settings": {
                "index": {
                    "number_of_shards": 2,
                    "number_of_replicas": 1,
                    "knn": True,
                }
            },
            "mappings": {
                "properties": {
                    "id":                    {"type": "keyword"},
                    "source_id":             {"type": "keyword"},
                    "chunk_index":           {"type": "integer"},
                    "pmid":                  {"type": "keyword"},
                    "doi":                   {"type": "keyword"},
                    "content_for_embedding": {"type": "text"},
                    "full_text":             {"type": "text"},
                    "title":                 {"type": "text"},
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": 768,
                        "method": {
                            "name": "hnsw",
                            "engine": "lucene",
                            "space_type": "cosinesimil",
                        },
                    },
                }
            },
        },
    )
    logger.info("New index created")

    # ------------------------------------------------------------------ #
    # Step 2: reindex with Painless script to populate source_id          #
    # ------------------------------------------------------------------ #
    logger.info("Reindexing '%s' → '%s' (may take a while)…", old_index, new_index)
    resp = client.reindex(
        body={
            "source": {"index": old_index},
            "dest":   {"index": new_index},
            "script": {
                "lang": "painless",
                # For old-format docs (no source_id): derive it from id by stripping :cN suffix.
                # For chunked docs (source_id already set): leave untouched.
                "source": (
                    "if (ctx._source.source_id == null || ctx._source.source_id == '') {"
                    "  String docId = ctx._source.id != null ? ctx._source.id : '';"
                    "  ctx._source.source_id = docId.replaceAll(':c\\\\d+$', '');"
                    "}"
                ),
            },
        },
        params={"wait_for_completion": "true"},
        request_timeout=3600,
    )

    total    = resp.get("total", 0)
    created  = resp.get("created", 0)
    updated  = resp.get("updated", 0)
    failures = resp.get("failures", [])
    logger.info(
        "Reindex complete — total=%d created=%d updated=%d failures=%d",
        total, created, updated, len(failures),
    )
    if failures:
        logger.error("Failures (first 5): %s", failures[:5])
        sys.exit(1)

    # ------------------------------------------------------------------ #
    # Step 3: delete old index                                             #
    # ------------------------------------------------------------------ #
    logger.info("Deleting old index '%s'…", old_index)
    client.indices.delete(index=old_index)

    # ------------------------------------------------------------------ #
    # Step 4: create alias so code needs no changes                       #
    # ------------------------------------------------------------------ #
    logger.info("Creating alias '%s' → '%s'…", old_index, new_index)
    client.indices.put_alias(index=new_index, name=old_index)

    logger.info(
        "Done. source_id is now keyword. "
        "Run backfill_chunks.py next to upgrade old-format docs to chunked schema."
    )


if __name__ == "__main__":
    main()
