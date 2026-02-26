import asyncio
import hashlib
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import quote_plus

import httpx

from src.classes.ollama_connector import OllamaConnector
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
    esearch_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&retmode=json&retmax={max_results}&sort=relevance&term={quote_plus(search_query)}"
    )

    try:
        esearch_resp = await client.get(esearch_url)
        esearch_resp.raise_for_status()
        id_list = (esearch_resp.json().get("esearchresult") or {}).get("idlist") or []
    except Exception:
        return []

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
    except Exception:
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
    return out


async def _search_crossref_sources(client: httpx.AsyncClient, terms: list[str], max_results: int = 4) -> list[dict]:
    if not terms:
        return []

    url = "https://api.crossref.org/works"
    params = {
        "query.bibliographic": " ".join(terms[:12]),
        "rows": max_results,
        "select": "DOI,title,abstract,URL",
    }
    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        items = (resp.json().get("message") or {}).get("items") or []
    except Exception:
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
                "claim_ids": [],
                "tags": ["primary_academic"],
                "abstract_source": "crossref",
                "url": item.get("URL") or (f"https://doi.org/{doi}" if doi else None),
            }
        )
        if len(out) >= max_results:
            break
    return out


def _embed_and_index_sources(sources: list[dict]) -> tuple[int, int]:
    if not sources:
        return 0, 0

    db = dbConnector()
    db.create_index("sources_index")
    indexed = 0
    skipped = 0
    seen_ids: set[str] = set()

    for source in sources:
        content = (source.get("content_for_embedding") or "").strip()
        if len(content) < 40:
            skipped += 1
            continue

        source_id = _stable_source_id(source)
        if source_id in seen_ids:
            skipped += 1
            continue
        seen_ids.add(source_id)

        try:
            doc = {
                "id": source_id,
                "index": "sources_index",
                "source_type": source.get("source_type") or "source",
                "pmid": source.get("pmid"),
                "doi": source.get("doi"),
                "title": source.get("title"),
                "content_for_embedding": content,
                "claim_ids": source.get("claim_ids") or [],
                "tags": source.get("tags") or ["primary_academic"],
                "abstract_source": source.get("abstract_source") or source.get("source_type"),
                "url": source.get("url"),
                "embedding": OllamaConnector.embed_text(content),
            }
            db.index_to_db("sources_index", doc)
            indexed += 1
        except Exception:
            skipped += 1

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
                "indexed": 0,
                "skipped": 0,
            }

        await emit("searching_pubmed", {"limit": 4})
        pubmed_task = asyncio.create_task(_search_pubmed_sources(client, terms, max_results=4))
        await emit("searching_crossref", {"limit": 4})
        crossref_task = asyncio.create_task(_search_crossref_sources(client, terms, max_results=4))
        pubmed_sources, crossref_sources = await asyncio.gather(
            pubmed_task,
            crossref_task,
        )

    await emit(
        "found_sources",
        {
            "pubmed_found": len(pubmed_sources),
            "crossref_found": len(crossref_sources),
            "total_found": len(pubmed_sources) + len(crossref_sources),
        },
    )

    merged_sources = [*pubmed_sources, *crossref_sources]
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
        "indexed": indexed,
        "skipped": skipped,
    }
