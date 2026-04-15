import asyncio
import hashlib
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import quote_plus

import httpx
import logging
import wikipediaapi

from src.classes.ollama_connector import OllamaConnector

logger = logging.getLogger(__name__)
from src.retrieval.db_connector import dbConnector
from src.xml_to_source import pubmed_article_xml_to_source

StageEmitter = Callable[[str, Dict[str, Any]], Awaitable[None]]


async def _emit_noop(stage: str, data: Dict[str, Any] | None = None) -> None:
    return


def _dedupe_terms(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        term = " ".join((item or "").split()).strip()
        key = term.lower()
        if not term or key in seen:
            continue
        seen.add(key)
        out.append(term)
    return out


def _strip_markup(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned or None


def _stable_source_id(source: dict) -> str:
    pmid = (source.get("pmid") or "").strip()
    doi = (source.get("doi") or "").strip().lower()
    url = (source.get("url") or "").strip()
    if pmid:
        return f"pmid:{pmid}"
    if doi:
        return f"doi:{doi}"
    if url:
        return "url:" + hashlib.sha1(url.encode("utf-8")).hexdigest()
    title = (source.get("title") or "").strip()
    content = (source.get("content_for_embedding") or "").strip()
    return "src:" + hashlib.sha1(f"{title}\n{content}".encode("utf-8")).hexdigest()


async def _spelling_correction(client: httpx.AsyncClient, nlp_url: str, text: str) -> str:
    text = " ".join((text or "").split()).strip()
    if not text:
        return ""

    candidate_paths = ("/spelling/correct", "/correct", "/spell")
    for path in candidate_paths:
        try:
            resp = await client.post(f"{nlp_url}{path}", json={"text": text})
            if resp.status_code >= 400:
                continue
            payload = resp.json() if resp.content else {}
            corrected = (
                payload.get("corrected")
                or payload.get("text")
                or payload.get("corrected_text")
            )
            if isinstance(corrected, str) and corrected.strip():
                return corrected.strip()
        except Exception:
            continue
    return text


async def _extract_terms_from_message(client: httpx.AsyncClient, nlp_url: str, text: str) -> list[str]:
    corrected = await _spelling_correction(client, nlp_url, text)
    if not corrected:
        return []
    try:
        resp = await client.post(f"{nlp_url}/extract", json={"text": corrected})
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return []

    expanded = payload.get("expanded_entities") or []
    entities = payload.get("entities") or []
    return _dedupe_terms([*expanded, *entities])


async def _search_pubmed_sources(client: httpx.AsyncClient, terms: list[str], max_results: int = 4) -> list[dict]:
    if not terms:
        return []

    search_query = " OR ".join(f"({t})" for t in terms[:12])
    logger.info(f"[pubmed] searching terms={terms[:5]} query='{search_query[:120]}'")

    esearch_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&retmode=json&retmax={max_results}&sort=relevance&term={quote_plus(search_query)}"
    )

    try:
        esearch_resp = await client.get(esearch_url)
        esearch_resp.raise_for_status()
        id_list = (esearch_resp.json().get("esearchresult") or {}).get("idlist") or []
    except Exception as e:
        logger.warning(f"[pubmed] esearch failed: {e}")
        return []

    logger.info(f"[pubmed] esearch returned {len(id_list)} ids: {id_list}")

    if not id_list:
        return []

    efetch_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pubmed&id={','.join(id_list[:max_results])}&retmode=xml"
    )

    try:
        efetch_resp = await client.get(efetch_url)
        efetch_resp.raise_for_status()
        root = ET.fromstring(efetch_resp.text)
    except Exception as e:
        logger.warning(f"[pubmed] efetch failed: {e}")
        return []

    out: list[dict] = []
    for article in root.findall(".//PubmedArticle"):
        try:
            source = pubmed_article_xml_to_source(ET.tostring(article, encoding="unicode"))
        except Exception:
            continue
        if not source.get("content_for_embedding"):
            continue
        source["source_type"] = "pubmed"
        source["abstract_source"] = source.get("abstract_source") or "pubmed"
        out.append(source)
        if len(out) >= max_results:
            break

    logger.info(f"[pubmed] fetched {len(out)} articles: {[s.get('pmid') or s.get('title','?')[:60] for s in out]}")
    return out


async def _search_crossref_sources(client: httpx.AsyncClient, terms: list[str], max_results: int = 4) -> list[dict]:
    if not terms:
        return []

    query = " ".join(terms[:12])
    logger.info(f"[crossref] searching query='{query[:120]}'")

    url = "https://api.crossref.org/works"
    params = {
        "query.bibliographic": query,
        "rows": max_results,
        "select": "DOI,title,abstract,URL",
    }
    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        items = (resp.json().get("message") or {}).get("items") or []
    except Exception as e:
        logger.warning(f"[crossref] request failed: {e}")
        return []

    out: list[dict] = []
    for item in items:
        doi = (item.get("DOI") or "").strip()
        title_arr = item.get("title") or []
        title = (title_arr[0] if isinstance(title_arr, list) and title_arr else "") or ""
        abstract = _strip_markup(item.get("abstract"))
        content_for_embedding = (
            f"{title}\n\n{abstract}".strip() if abstract else title.strip()
        )
        if not content_for_embedding:
            continue
        out.append(
            {
                "source_type": "crossref",
                "pmid": None,
                "doi": doi or None,
                "title": title or None,
                "content_for_embedding": content_for_embedding,
                "tags": ["primary_academic"],
                "abstract_source": "crossref",
                "url": item.get("URL") or (f"https://doi.org/{doi}" if doi else None),
            }
        )
        if len(out) >= max_results:
            break

    logger.info(f"[crossref] fetched {len(out)} items: {[s.get('doi') or s.get('title','?')[:60] for s in out]}")
    return out


_wiki = wikipediaapi.Wikipedia(
    user_agent="cancerbot/1.0 (medical-rag-assistant)",
    language="en",
    extract_format=wikipediaapi.ExtractFormat.WIKI,
)


async def _search_wikipedia_sources(terms: list[str], max_results: int = 3) -> list[dict]:
    if not terms:
        return []

    logger.info(f"[wikipedia] searching terms={terms[:5]}")

    def _fetch() -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()
        for term in terms[:10]:
            if len(out) >= max_results:
                break
            try:
                logger.debug(f"[wikipedia] fetching page for term='{term}'")
                page = _wiki.page(term)
                if not page.exists():
                    logger.debug(f"[wikipedia] page not found for term='{term}'")
                    continue
                if page.title in seen:
                    continue
                seen.add(page.title)
                summary = (page.summary or "").strip()
                if len(summary) < 80:
                    logger.debug(f"[wikipedia] page '{page.title}' summary too short ({len(summary)} chars), skipping")
                    continue
                logger.info(f"[wikipedia] found page='{page.title}' url={page.fullurl}")
                out.append(
                    {
                        "source_type": "wikipedia",
                        "pmid": None,
                        "doi": None,
                        "title": page.title,
                        "content_for_embedding": f"{page.title}\n\n{summary}",
                        "tags": ["wikipedia"],
                        "abstract_source": "wikipedia",
                        "url": page.fullurl,
                    }
                )
            except Exception as e:
                logger.warning(f"[wikipedia] error fetching term='{term}': {e}")
                continue

        logger.info(f"[wikipedia] done: fetched {len(out)} pages")
        return out

    return await asyncio.to_thread(_fetch)


def _embed_and_index_sources(sources: list[dict]) -> tuple[int, int]:
    if not sources:
        return 0, 0

    logger.info(f"[index] embedding and indexing {len(sources)} sources")
    db = dbConnector()
    db.create_index("sources_index")
    indexed = 0
    skipped = 0

    # Assign stable IDs and deduplicate within the batch
    candidate: list[tuple[str, dict]] = []
    seen_ids: set[str] = set()
    for source in sources:
        content = (source.get("content_for_embedding") or "").strip()
        if len(content) < 40:
            logger.debug(f"[index] skipping source '{source.get('title','?')[:60]}' — content too short")
            skipped += 1
            continue
        source_id = _stable_source_id(source)
        if source_id in seen_ids:
            logger.debug(f"[index] skipping duplicate id={source_id}")
            skipped += 1
            continue
        seen_ids.add(source_id)
        candidate.append((source_id, source))

    # Check which IDs already exist in OpenSearch
    already_indexed = db.existing_source_ids([sid for sid, _ in candidate])
    if already_indexed:
        logger.info(f"[index] {len(already_indexed)} sources already in index, skipping: {list(already_indexed)}")

    for source_id, source in candidate:
        if source_id in already_indexed:
            skipped += 1
            continue
        content = (source.get("content_for_embedding") or "").strip()

        try:
            doc = {
                "id": source_id,
                "index": "sources_index",
                "source_type": source.get("source_type") or "source",
                "pmid": source.get("pmid"),
                "doi": source.get("doi"),
                "title": source.get("title"),
                "content_for_embedding": content,
                "tags": source.get("tags") or ["primary_academic"],
                "abstract_source": source.get("abstract_source") or source.get("source_type"),
                "url": source.get("url"),
                "embedding": OllamaConnector.embed_text(content),
            }
            db.index_to_db("sources_index", doc)
            logger.info(f"[index] indexed id={source_id} title='{source.get('title','?')[:60]}' type={source.get('source_type')}")
            indexed += 1
        except Exception as e:
            logger.warning(f"[index] failed to index source '{source.get('title','?')[:60]}': {e}")
            skipped += 1

    logger.info(f"[index] done: indexed={indexed} skipped={skipped}")
    return indexed, skipped


async def search_and_embed(
    conversation,
    emit: StageEmitter = _emit_noop,
) -> dict[str, Any]:
    messages = list(getattr(conversation, "messages", []) or [])
    last_messages = messages[-4:]
    texts = [str(getattr(m, "content", "") or "").strip() for m in last_messages]
    texts = [t for t in texts if t]

    await emit("analyzing_recent_messages", {"messages_considered": len(texts)})
    if not texts:
        return {
            "terms": [],
            "pubmed_found": 0,
            "crossref_found": 0,
            "indexed": 0,
            "skipped": 0,
        }

    nlp_url = (os.getenv("NLP_URL", "http://127.0.0.1:8011") or "").strip().strip("\"'")
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        await emit("extracting_search_terms", {"source": "cancerbot-nlp"})
        term_batches = await asyncio.gather(
            *[_extract_terms_from_message(client, nlp_url, t) for t in texts],
            return_exceptions=True,
        )

        terms: list[str] = []
        for batch in term_batches:
            if isinstance(batch, Exception):
                continue
            terms.extend(batch)
        terms = _dedupe_terms(terms)
        await emit("terms_ready", {"terms_count": len(terms), "terms": terms[:20]})
        if not terms:
            return {
                "terms": [],
                "pubmed_found": 0,
                "crossref_found": 0,
                "wikipedia_found": 0,
                "indexed": 0,
                "skipped": 0,
            }

        await emit("searching_pubmed", {"limit": 4})
        await emit("searching_crossref", {"limit": 4})
        await emit("searching_wikipedia", {"limit": 3})
        pubmed_sources, crossref_sources, wikipedia_sources = await asyncio.gather(
            asyncio.create_task(_search_pubmed_sources(client, terms, max_results=4)),
            asyncio.create_task(_search_crossref_sources(client, terms, max_results=4)),
            _search_wikipedia_sources(terms, max_results=3),
        )

    await emit(
        "found_sources",
        {
            "pubmed_found": len(pubmed_sources),
            "crossref_found": len(crossref_sources),
            "wikipedia_found": len(wikipedia_sources),
            "total_found": len(pubmed_sources) + len(crossref_sources) + len(wikipedia_sources),
        },
    )

    merged_sources = [*pubmed_sources, *crossref_sources, *wikipedia_sources]
    await emit("embedding_and_indexing_sources", {"total_sources": len(merged_sources)})
    indexed, skipped = await asyncio.to_thread(_embed_and_index_sources, merged_sources)
    await emit(
        "sources_indexed",
        {"indexed": indexed, "skipped": skipped},
    )

    return {
        "terms": terms,
        "pubmed_found": len(pubmed_sources),
        "crossref_found": len(crossref_sources),
        "wikipedia_found": len(wikipedia_sources),
        "indexed": indexed,
        "skipped": skipped,
    }
