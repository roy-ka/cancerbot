#!/usr/bin/env python3
"""
Migration: re-fetch and re-clean all CrossRef-sourced documents in OpenSearch.

Older CrossRef abstracts were stored either completely raw (JATS XML tags intact,
via the now-removed offline enricher) or with a blunt regex tag-strip that left the
JATS "<jats:title>Abstract</jats:title>" label as a stray "Abstract " prefix in the
text (via the live search path's old _strip_markup). Both are fixed going forward
by _clean_crossref_abstract, but existing indexed content needs to be reprocessed.

For each unique source_id with source_type == "crossref":
  1. Re-resolve the DOI via CrossRef (falling back to PubMed) for a clean title +
     abstract using _resolve_doi (already uses _clean_crossref_abstract).
  2. If there's word budget left (content_for_embedding under MAX_FULLTEXT_WORDS),
     try Unpaywall for an open-access full-text excerpt to fill the remainder.
  3. Re-chunk the combined text into 150-word/40-word-overlap sections.
  4. Delete the source's existing chunks and re-index the new ones.

Sources that fail to re-resolve (network error, DOI no longer found) are left
untouched rather than deleted, so a bad run can't destroy existing data.

Safe to re-run: each source is always fully re-fetched and re-chunked from scratch.
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

import httpx

from src.retrieval.db_connector import dbConnector
from src.classes.embedding_connector import EmbeddingConnector
from src.routers.conversation_helper import (
    _chunk_text,
    _resolve_doi,
    _fetch_oa_fulltext_excerpt,
    MAX_FULLTEXT_WORDS,
)

_SCROLL_TTL = "5m"
_BATCH_SIZE = 100
_REQUEST_DELAY_SECONDS = 0.5  # be polite to CrossRef/Unpaywall


def _scroll_crossref_docs(db_client, index_name):
    """Yield all docs with source_type == 'crossref' via scroll."""
    scroll_id = None
    try:
        resp = db_client.search(
            index=index_name,
            scroll=_SCROLL_TTL,
            body={
                "size": _BATCH_SIZE,
                "_source": ["id", "source_id", "doi", "url", "tags", "pmid"],
                "query": {"term": {"source_type": "crossref"}},
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


async def _rebuild_source(client: httpx.AsyncClient, doi: str) -> dict | None:
    """Re-resolve a DOI into {title, content}, content capped at MAX_FULLTEXT_WORDS, or None on failure."""
    resolved = await _resolve_doi(client, doi)
    if not resolved or not resolved.get("title"):
        return None

    title = resolved["title"]
    abstract = resolved.get("abstract") or ""
    content = f"{title}\n\n{abstract}".strip() if abstract else title.strip()

    remaining = MAX_FULLTEXT_WORDS - len(content.split())
    if remaining > 0:
        excerpt = await _fetch_oa_fulltext_excerpt(client, doi, resolved.get("url"), remaining)
        if excerpt:
            content = f"{content}\n\n{excerpt}".strip()

    return {"title": title, "content": content}


async def main(limit: int | None, dry_run: bool) -> None:
    logger.info("Initialising OpenSearch connection…")
    dbConnector._initialize()
    if not dbConnector.db_client:
        logger.error("OpenSearch not available — aborting")
        sys.exit(1)

    index_name = dbConnector._model["sources_index"]

    # Collect one representative doc per unique source_id (chunks share source_id/doi/tags).
    sources: dict[str, dict] = {}
    for hit in _scroll_crossref_docs(dbConnector.db_client, index_name):
        doc = hit.get("_source", {})
        source_id = doc.get("source_id") or doc.get("id")
        if not source_id or source_id in sources:
            continue
        doi = (doc.get("doi") or "").strip()
        if not doi and source_id.startswith("doi:"):
            doi = source_id[len("doi:"):]
        if not doi:
            logger.warning("No DOI for source_id=%s — skipping", source_id)
            continue
        sources[source_id] = {"doi": doi, "tags": doc.get("tags") or [], "pmid": doc.get("pmid")}
        if limit and len(sources) >= limit:
            break

    logger.info("Found %d unique CrossRef source(s) to reprocess", len(sources))

    rebuilt = skipped = errors = 0

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        for source_id, meta in sources.items():
            doi = meta["doi"]
            try:
                rebuilt_source = await _rebuild_source(client, doi)
            except Exception as exc:
                logger.error("Failed to rebuild %s (doi=%s): %s", source_id, doi, exc)
                errors += 1
                await asyncio.sleep(_REQUEST_DELAY_SECONDS)
                continue

            if not rebuilt_source:
                logger.warning("Could not re-resolve %s (doi=%s) — leaving existing chunks untouched", source_id, doi)
                skipped += 1
                await asyncio.sleep(_REQUEST_DELAY_SECONDS)
                continue

            title, content = rebuilt_source["title"], rebuilt_source["content"]
            chunks = _chunk_text(content)
            logger.info("Rebuilt %s (doi=%s) — %d word(s), %d chunk(s)", source_id, doi, len(content.split()), len(chunks))

            if dry_run:
                logger.info("[dry-run] %s new content preview: %r", source_id, content[:200])
                rebuilt += 1
                await asyncio.sleep(_REQUEST_DELAY_SECONDS)
                continue

            try:
                deleted = dbConnector.delete_chunks_by_source_id(source_id)
                logger.info("Deleted %d old chunk(s) for %s", deleted, source_id)

                for chunk_index, chunk_text in enumerate(chunks):
                    embedding = EmbeddingConnector.embed_text(chunk_text)
                    dbConnector.index_to_db(
                        "sources_index",
                        {
                            "id": f"{source_id}:c{chunk_index}",
                            "source_id": source_id,
                            "chunk_index": chunk_index,
                            "source_type": "crossref",
                            "pmid": meta["pmid"],
                            "doi": doi,
                            "title": title,
                            "full_text": content,
                            "content_for_embedding": chunk_text,
                            "tags": meta["tags"],
                            "abstract_source": "crossref",
                            "url": f"https://doi.org/{doi}",
                            "embedding": embedding,
                        },
                    )
                rebuilt += 1
            except Exception as exc:
                logger.error("Failed to re-index %s: %s", source_id, exc)
                errors += 1

            await asyncio.sleep(_REQUEST_DELAY_SECONDS)

    logger.info(
        "Done — rebuilt=%d  skipped=%d  errors=%d%s",
        rebuilt, skipped, errors, " (dry-run, nothing written)" if dry_run else "",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N sources (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Preview rebuilt content without writing to OpenSearch")
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.dry_run))
