#!/usr/bin/env python3
"""
One-off cleanup: remove sources double-indexed under two different base_id
schemes for the same real article.

_stable_source_id (src/routers/conversation_helper.py) prefers pmid over
doi, so the same paper can end up indexed twice: once as pmid:X (fetched via
PubMed) and once as doi:Y (fetched via CrossRef, which has no pmid).
existing_base_source_ids only catches an *exact* base_id match, so it can't
see these are the same article — existing_doi_base_ids (added alongside this
script) now prevents *new* duplicates of this kind at index time. This
script sweeps out what was already indexed before that fix landed.

For each DOI reachable under more than one base_id, one base_id is kept and
the rest are deleted (all their chunks). The keeper is chosen by the same
priority _stable_source_id itself uses to assign new IDs (pmid > doi > nct >
url > src), so the surviving ID matches what indexing would produce today.

Not run automatically by deploy.sh — this is a manual, one-off backfill
against index state from before the double-indexing fix, not a repeating
migration (a scan when the fix landed found 371 sources / 299 distinct DOIs
/ zero reachable under more than one source_id at that corpus size — see
CLAUDE.md's Retrieval section — so this may find nothing to do).

Usage:
  python scripts/remove_duplicate_doi_sources.py              # dry run (default)
  python scripts/remove_duplicate_doi_sources.py --execute    # actually delete
  python scripts/remove_duplicate_doi_sources.py --execute --limit 50
"""
import argparse
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from src.retrieval.db_connector import dbConnector

_SCROLL_TTL = "5m"
_BATCH_SIZE = 200

# Mirrors _stable_source_id's own assignment priority (pmid > doi > nct >
# url > src) so the base_id this script keeps is the one indexing would
# produce today, not an arbitrary survivor.
_BASE_ID_PRIORITY = {"pmid": 0, "doi": 1, "nct": 2, "url": 3, "src": 4}


def _priority(base_id: str) -> int:
    prefix = base_id.split(":", 1)[0]
    return _BASE_ID_PRIORITY.get(prefix, 99)


def group_duplicates_by_doi(doi_to_base_ids: dict) -> dict:
    """For each DOI reachable under 2+ base_ids, pick a keeper and return
    {doi: (keeper_base_id, {loser_base_ids})}. DOIs with only one base_id
    are omitted (nothing to do).
    """
    result = {}
    for doi, base_ids in doi_to_base_ids.items():
        if len(base_ids) < 2:
            continue
        ordered = sorted(base_ids, key=lambda b: (_priority(b), b))
        keeper, losers = ordered[0], set(ordered[1:])
        result[doi] = (keeper, losers)
    return result


def _scroll_all_docs(db_client, index_name):
    scroll_id = None
    try:
        resp = db_client.search(
            index=index_name,
            scroll=_SCROLL_TTL,
            body={
                "size": _BATCH_SIZE,
                "_source": ["id", "source_id", "doi"],
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

    logger.info("Scanning '%s' for DOIs indexed under more than one base_id…", index_name)
    doi_to_base_ids: dict[str, set] = {}
    # Whether a base_id's docs carry a `source_id` field (chunked schema,
    # deleted via delete_chunks_by_source_id) or not (legacy pre-chunked
    # doc, deleted via delete_source_by_id — exact id match). Mirrors
    # remove_short_sources.py's same split.
    base_id_is_legacy: dict[str, bool] = {}
    scanned = 0
    for hit in _scroll_all_docs(client, index_name):
        scanned += 1
        source = hit["_source"]
        doi = (source.get("doi") or "").strip().lower()
        if not doi:
            continue
        source_id = source.get("source_id")
        doc_id = source.get("id") or ""
        base_id = source_id or re.sub(r":c\d+$", "", doc_id)
        if not base_id:
            continue
        doi_to_base_ids.setdefault(doi, set()).add(base_id)
        base_id_is_legacy.setdefault(base_id, not bool(source_id))

    logger.info("Scanned %d doc(s), %d distinct DOI(s) seen", scanned, len(doi_to_base_ids))

    duplicates = group_duplicates_by_doi(doi_to_base_ids)
    logger.info("Found %d DOI(s) reachable under more than one base_id", len(duplicates))

    to_delete: list[tuple[str, str, str]] = []  # (doi, keeper, loser)
    for doi, (keeper, losers) in duplicates.items():
        for loser in losers:
            to_delete.append((doi, keeper, loser))
    if limit:
        to_delete = to_delete[:limit]

    if not execute:
        for doi, keeper, loser in to_delete:
            logger.info("[dry-run] doi=%s — would keep %s, delete %s", doi, keeper, loser)
        logger.info("Dry run — nothing deleted. Re-run with --execute to delete.")
        return

    deleted_sources = 0
    deleted_chunks = 0
    for doi, keeper, loser in to_delete:
        if base_id_is_legacy.get(loser):
            n = dbConnector.delete_source_by_id(loser)
        else:
            n = dbConnector.delete_chunks_by_source_id(loser)
        logger.info("doi=%s — kept %s, deleted %s (%d doc(s) removed)", doi, keeper, loser, n)
        deleted_sources += 1
        deleted_chunks += n

    logger.info("Done — duplicate_sources_deleted=%d docs_deleted=%d", deleted_sources, deleted_chunks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N duplicate base_ids (for testing)")
    parser.add_argument("--execute", action="store_true", help="Actually delete. Without this flag, only reports what would be deleted.")
    args = parser.parse_args()
    main(args.limit, args.execute)
