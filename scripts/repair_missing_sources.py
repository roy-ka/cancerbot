#!/usr/bin/env python3
"""
Migration: find and repair source citations that exist in PostgreSQL messages
but are missing from the OpenSearch sources index.

Background: a one-time index remapping migration (fix_source_id_mapping.py,
since removed) did a reindex-then-delete-old-index swap against a live index
that's continuously written to by chat traffic. Any source indexed during that
window landed nowhere — not in the pre-migration snapshot, and gone once the
old index was deleted. Messages still cite these source IDs, but the docs
behind them no longer exist.

For each source ID referenced by any message but absent from OpenSearch:
  - doi:<doi>   — re-resolved via CrossRef → PubMed fallback (_resolve_doi),
                  optionally supplemented with an Unpaywall OA full-text
                  excerpt, same pipeline as fix_crossref_abstracts.py.
  - pmid:<pmid> — re-fetched directly from PubMed (_fetch_pubmed_by_pmid).
  - url:<sha1>  — NOT recoverable. The ID is a one-way hash of the original
                  URL; there's nothing in Postgres to reverse it from. These
                  are reported, not repaired.

Each repaired source is re-chunked (150-word/40-word-overlap) and indexed
fresh — there's nothing to delete first since these documents don't exist yet.

Safe to re-run: sources that already exist are skipped (checked via
dbConnector.existing_base_source_ids), so a repeat run only touches whatever
is still missing.
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

from src.db.session import SessionLocal
from src.db.models import Message
from src.retrieval.db_connector import dbConnector
from src.classes.ollama_connector import OllamaConnector
from src.routers.conversation_helper import (
    _chunk_text,
    _resolve_doi,
    _fetch_oa_fulltext_excerpt,
    _fetch_pubmed_by_pmid,
    MAX_FULLTEXT_WORDS,
)

_EXISTENCE_CHECK_BATCH = 500
_REQUEST_DELAY_SECONDS = 0.5  # be polite to CrossRef/PubMed/Unpaywall


def _collect_referenced_source_ids() -> dict[str, int]:
    """Return {source_id: reference_count} across every assistant message."""
    counts: dict[str, int] = {}
    with SessionLocal() as session:
        messages = (
            session.query(Message)
            .filter(Message.role == "assistant", Message.sources_ids.isnot(None))
            .all()
        )
        logger.info("Scanned %d assistant messages with sources_ids", len(messages))
        for msg in messages:
            for sid in msg.source_ids:
                sid = (sid or "").strip()
                if sid:
                    counts[sid] = counts.get(sid, 0) + 1
    return counts


def _find_missing(all_ids: list[str]) -> set[str]:
    """Return the subset of all_ids that have no chunks in OpenSearch, batched."""
    missing: set[str] = set()
    for i in range(0, len(all_ids), _EXISTENCE_CHECK_BATCH):
        batch = all_ids[i : i + _EXISTENCE_CHECK_BATCH]
        found = dbConnector.existing_base_source_ids(batch)
        missing.update(bid for bid in batch if bid not in found)
    return missing


async def _repair_doi(client: httpx.AsyncClient, source_id: str, doi: str) -> bool:
    resolved = await _resolve_doi(client, doi)
    if not resolved or not resolved.get("title"):
        return False

    title = resolved["title"]
    abstract = resolved.get("abstract") or ""
    content = f"{title}\n\n{abstract}".strip() if abstract else title.strip()

    remaining = MAX_FULLTEXT_WORDS - len(content.split())
    if remaining > 0:
        excerpt = await _fetch_oa_fulltext_excerpt(client, doi, resolved.get("url"), remaining)
        if excerpt:
            content = f"{content}\n\n{excerpt}".strip()

    _index_chunks(source_id, content, source_type="crossref", pmid=None, doi=doi, title=title)
    return True


async def _repair_pmid(client: httpx.AsyncClient, source_id: str, pmid: str) -> bool:
    source = await _fetch_pubmed_by_pmid(client, pmid)
    content = (source or {}).get("content_for_embedding")
    if not source or not content:
        return False

    _index_chunks(
        source_id, content, source_type="pubmed",
        pmid=pmid, doi=source.get("doi"), title=source.get("title"),
    )
    return True


def _index_chunks(source_id: str, content: str, *, source_type: str, pmid: str | None, doi: str | None, title: str | None) -> None:
    chunks = _chunk_text(content)
    for chunk_index, chunk_text in enumerate(chunks):
        embedding = OllamaConnector.embed_text(chunk_text)
        dbConnector.index_to_db(
            "sources_index",
            {
                "id": f"{source_id}:c{chunk_index}",
                "source_id": source_id,
                "chunk_index": chunk_index,
                "source_type": source_type,
                "pmid": pmid,
                "doi": doi,
                "title": title,
                "full_text": content,
                "content_for_embedding": chunk_text,
                "tags": ["primary_academic"],
                "abstract_source": source_type,
                "url": (f"https://doi.org/{doi}" if doi else (f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None)),
                "embedding": embedding,
            },
        )
    logger.info("Indexed %s — %d word(s), %d chunk(s)", source_id, len(content.split()), len(chunks))


async def main(limit: int | None, dry_run: bool) -> None:
    logger.info("Initialising OpenSearch connection…")
    dbConnector._initialize()
    if not dbConnector.db_client:
        logger.error("OpenSearch not available — aborting")
        sys.exit(1)

    logger.info("Scanning PostgreSQL for referenced source IDs…")
    ref_counts = _collect_referenced_source_ids()
    all_ids = sorted(ref_counts)
    logger.info("Found %d unique source ID(s) referenced across all messages", len(all_ids))

    missing = sorted(_find_missing(all_ids))
    logger.info("%d referenced source ID(s) are missing from OpenSearch", len(missing))

    doi_ids = [sid for sid in missing if sid.startswith("doi:")]
    pmid_ids = [sid for sid in missing if sid.startswith("pmid:")]
    url_ids = [sid for sid in missing if sid.startswith("url:")]
    other_ids = [sid for sid in missing if sid not in doi_ids and sid not in pmid_ids and sid not in url_ids]

    logger.info(
        "Breakdown — doi=%d pmid=%d url=%d (unrecoverable) other=%d",
        len(doi_ids), len(pmid_ids), len(url_ids), len(other_ids),
    )
    if url_ids:
        logger.warning(
            "%d url: source(s) cannot be repaired (hash is one-way, original URL unknown): %s",
            len(url_ids), url_ids[:20],
        )
    if other_ids:
        logger.warning("%d source(s) have an unrecognized ID format, skipping: %s", len(other_ids), other_ids[:20])

    repairable = doi_ids + pmid_ids
    if limit:
        repairable = repairable[:limit]

    repaired = failed = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        for source_id in repairable:
            try:
                if source_id.startswith("doi:"):
                    ok = await _repair_doi_wrapper(client, source_id, dry_run)
                else:
                    ok = await _repair_pmid_wrapper(client, source_id, dry_run)
            except Exception as exc:
                logger.error("Failed to repair %s: %s", source_id, exc)
                ok = False

            if ok:
                repaired += 1
            else:
                failed += 1
                logger.warning("Could not re-resolve %s — cited %d time(s), still missing", source_id, ref_counts[source_id])

            await asyncio.sleep(_REQUEST_DELAY_SECONDS)

    logger.info(
        "Done — repaired=%d  failed=%d  unrecoverable(url)=%d  unrecognized=%d%s",
        repaired, failed, len(url_ids), len(other_ids),
        " (dry-run, nothing written)" if dry_run else "",
    )


async def _repair_doi_wrapper(client: httpx.AsyncClient, source_id: str, dry_run: bool) -> bool:
    doi = source_id[len("doi:"):]
    if dry_run:
        resolved = await _resolve_doi(client, doi)
        ok = bool(resolved and resolved.get("title"))
        logger.info("[dry-run] %s -> %s", source_id, "resolvable" if ok else "NOT resolvable")
        return ok
    return await _repair_doi(client, source_id, doi)


async def _repair_pmid_wrapper(client: httpx.AsyncClient, source_id: str, dry_run: bool) -> bool:
    pmid = source_id[len("pmid:"):]
    if dry_run:
        source = await _fetch_pubmed_by_pmid(client, pmid)
        ok = bool(source and source.get("content_for_embedding"))
        logger.info("[dry-run] %s -> %s", source_id, "resolvable" if ok else "NOT resolvable")
        return ok
    return await _repair_pmid(client, source_id, pmid)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only repair the first N sources (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be repaired without writing to OpenSearch")
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.dry_run))
