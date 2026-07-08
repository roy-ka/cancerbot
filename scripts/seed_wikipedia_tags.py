#!/usr/bin/env python3
"""
Backfill wikipedia:term:<title> tags on existing Wikipedia sources in OpenSearch.

Existing documents only carry the generic "wikipedia" tag. This script adds a
per-term tag so _search_wikipedia_sources can skip the Wikipedia API call for
terms whose page is already indexed.

Safe to run multiple times — skips documents that already have a term tag.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    from src.retrieval.db_connector import dbConnector

    dbConnector._initialize()
    client = dbConnector.db_client
    if not client:
        logger.warning("[seed:wikipedia_tags] OpenSearch not available — skipping")
        return

    index = dbConnector._model["sources_index"]
    updated = skipped = errors = 0

    resp = client.search(
        index=index,
        body={
            "query": {"term": {"source_type.keyword": "wikipedia"}},
            "_source": ["title", "tags"],
            "size": 200,
        },
        scroll="2m",
    )
    scroll_id = resp.get("_scroll_id")
    hits = resp["hits"]["hits"]
    total = resp["hits"]["total"]["value"]
    logger.info("[seed:wikipedia_tags] %d Wikipedia documents found", total)

    while hits:
        for hit in hits:
            src = hit.get("_source", {})
            title = (src.get("title") or "").strip()
            if not title:
                skipped += 1
                continue

            existing_tags = src.get("tags") or []
            if any(t.startswith("wikipedia:term:") for t in existing_tags):
                skipped += 1
                continue

            term_tag = f"wikipedia:term:{title.lower()}"
            try:
                client.update(
                    index=index,
                    id=hit["_id"],
                    body={
                        "script": {
                            "source": (
                                "if (ctx._source.tags == null) {"
                                "  ctx._source.tags = new ArrayList();"
                                "}"
                                "if (!ctx._source.tags.contains(params.tag)) {"
                                "  ctx._source.tags.add(params.tag);"
                                "}"
                            ),
                            "params": {"tag": term_tag},
                        }
                    },
                )
                updated += 1
            except Exception as e:
                logger.warning("[seed:wikipedia_tags] update failed for '%s': %s", title, e)
                errors += 1

        resp = client.scroll(scroll_id=scroll_id, scroll="2m")
        scroll_id = resp.get("_scroll_id")
        hits = resp["hits"]["hits"]

    try:
        if scroll_id:
            client.clear_scroll(scroll_id=scroll_id)
    except Exception:
        pass

    logger.info(
        "[seed:wikipedia_tags] done — updated=%d skipped=%d errors=%d",
        updated, skipped, errors,
    )


if __name__ == "__main__":
    main()
