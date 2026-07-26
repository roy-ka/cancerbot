#!/usr/bin/env python3
"""
Migration: backfill pub_year / pub_types / evidence_level onto existing
OpenSearch source docs.

src/retrieval/search.py boosts sources by evidence level (meta-analysis > RCT
> case report) and publication recency, and hard-excludes editorials/errata/
retractions. Docs indexed before those fields existed have none of them.

Unlike full_text_word_count, this metadata is NOT recoverable from the index
itself — it has to be re-fetched from PubMed. This script scrolls the sources
index for docs that have a `pmid` but no `evidence_level`, re-fetches their
publication metadata from PubMed efetch in batches, and updates every chunk
of each affected source.

CrossRef-only and Wikipedia/URL sources are skipped: they have no pmid to
re-fetch by. That's harmless — search.py's boosts are `should` clauses and
its pub-type exclusion is a `must_not`, so a doc without these fields is
ranked lower but never filtered out.

Safe to re-run: only docs still missing `evidence_level` are touched.
"""
import argparse
import asyncio
import logging
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

import httpx

from src.retrieval.db_connector import dbConnector
from src.routers.conversation_helper import (
    _coerce_pub_year,
    _derive_evidence_level,
    _normalise_pub_types,
    _retry_get,
)

_SCROLL_TTL = "5m"
_SCROLL_BATCH = 500
_EFETCH_BATCH = 100          # PubMed allows a few hundred ids per efetch
_REQUEST_DELAY_SECONDS = 0.4  # stay well under NCBI's rate limit


def _scroll_docs_missing_metadata(db_client, index_name):
    """Yield docs that have a pmid but no evidence_level yet."""
    scroll_id = None
    try:
        resp = db_client.search(
            index=index_name,
            scroll=_SCROLL_TTL,
            body={
                "size": _SCROLL_BATCH,
                "_source": ["id", "source_id", "pmid"],
                "query": {
                    "bool": {
                        "must": [{"exists": {"field": "pmid"}}],
                        "must_not": [{"exists": {"field": "evidence_level"}}],
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


def _parse_efetch(xml_text: str) -> dict[str, dict]:
    """Return {pmid: {"pub_year": int|None, "pub_types": [str]}} from an efetch response."""
    out: dict[str, dict] = {}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("efetch response was not parseable XML: %s", exc)
        return out

    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find("./MedlineCitation/PMID")
        if pmid_el is None or not (pmid_el.text or "").strip():
            continue
        pmid = pmid_el.text.strip()

        year_el = article.find("./MedlineCitation/Article/Journal/JournalIssue/PubDate/Year")
        year = _coerce_pub_year(year_el.text) if year_el is not None else None
        if year is None:
            # Some records only carry a MedlineDate like "2019 Nov-Dec"
            medline_el = article.find("./MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate")
            if medline_el is not None:
                year = _coerce_pub_year(medline_el.text)

        pub_types = [
            (pt.text or "").strip()
            for pt in article.findall("./MedlineCitation/Article/PublicationTypeList/PublicationType")
            if (pt.text or "").strip()
        ]
        out[pmid] = {"pub_year": year, "pub_types": _normalise_pub_types(pub_types)}
    return out


async def _fetch_metadata(client: httpx.AsyncClient, pmids: list[str]) -> dict[str, dict]:
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pubmed&id={','.join(pmids)}&retmode=xml"
    )
    resp = await _retry_get(client, url)
    resp.raise_for_status()
    return _parse_efetch(resp.text)


def _update_source_chunks(client, index_name: str, pmid: str, meta: dict) -> int:
    """Set the metadata fields on every chunk belonging to this pmid."""
    res = client.update_by_query(
        index=index_name,
        body={
            "query": {"term": {"pmid": pmid}},
            "script": {
                "lang": "painless",
                "source": (
                    "ctx._source.pub_year = params.pub_year;"
                    "ctx._source.pub_types = params.pub_types;"
                    "ctx._source.evidence_level = params.evidence_level;"
                ),
                "params": {
                    "pub_year": meta["pub_year"],
                    "pub_types": meta["pub_types"],
                    "evidence_level": meta["evidence_level"],
                },
            },
        },
        params={"wait_for_completion": "true"},
        request_timeout=300,
    )
    return res.get("updated", 0)


async def main(limit: int | None, dry_run: bool) -> None:
    logger.info("Initialising OpenSearch connection…")
    dbConnector._initialize()
    db_client = dbConnector.db_client
    if not db_client:
        logger.error("OpenSearch not available — aborting")
        sys.exit(1)

    index_name = dbConnector._model["sources_index"]

    logger.info("Scanning '%s' for pmid docs without evidence_level…", index_name)
    pmids: list[str] = []
    seen: set[str] = set()
    for hit in _scroll_docs_missing_metadata(db_client, index_name):
        pmid = str(hit["_source"].get("pmid") or "").strip()
        if pmid and pmid not in seen:
            seen.add(pmid)
            pmids.append(pmid)

    logger.info("%d unique pmid source(s) need metadata", len(pmids))
    if limit:
        pmids = pmids[:limit]

    if dry_run:
        logger.info("[dry-run] would fetch metadata for %d pmid(s): %s", len(pmids), pmids[:20])
        logger.info("Dry run — nothing changed. Re-run without --dry-run to apply.")
        return

    updated_sources = updated_chunks = failed = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http_client:
        for i in range(0, len(pmids), _EFETCH_BATCH):
            batch = pmids[i : i + _EFETCH_BATCH]
            try:
                metadata = await _fetch_metadata(http_client, batch)
            except Exception as exc:
                logger.warning("efetch failed for batch starting at %d: %s", i, exc)
                failed += len(batch)
                continue

            for pmid in batch:
                meta = metadata.get(pmid)
                if not meta:
                    logger.debug("no metadata returned for pmid=%s", pmid)
                    failed += 1
                    continue
                meta["evidence_level"] = _derive_evidence_level(meta["pub_types"])
                try:
                    n = _update_source_chunks(db_client, index_name, pmid, meta)
                    updated_sources += 1
                    updated_chunks += n
                    logger.info(
                        "Updated pmid=%s year=%s evidence=%d chunks=%d",
                        pmid, meta["pub_year"], meta["evidence_level"], n,
                    )
                except Exception as exc:
                    logger.warning("update failed for pmid=%s: %s", pmid, exc)
                    failed += 1

            await asyncio.sleep(_REQUEST_DELAY_SECONDS)

    logger.info(
        "Done — sources_updated=%d chunks_updated=%d failed=%d",
        updated_sources, updated_chunks, failed,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N pmids (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be fetched without writing")
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.dry_run))
