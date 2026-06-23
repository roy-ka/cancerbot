import asyncio
import hashlib
import ipaddress
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import quote_plus, urlparse
import httpx
import logging
import wikipediaapi

from src.classes.ollama_connector import OllamaConnector

logger = logging.getLogger(__name__)
from src.retrieval.db_connector import dbConnector
from src.xml_to_source import pubmed_article_xml_to_source

StageEmitter = Callable[[str, Dict[str, Any]], Awaitable[None]]

_URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]
_BLOCKED_HOSTS = frozenset({"localhost", "localhost."})
_MAX_MESSAGE_URLS = 3


def _is_safe_url(url: str) -> bool:
    """Return True only for http/https URLs that don't target private/internal networks."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if not host or host in _BLOCKED_HOSTS:
            return False
        try:
            addr = ipaddress.ip_address(host)
            return not any(addr in net for net in _PRIVATE_NETS)
        except ValueError:
            return True
    except Exception:
        return False


_SPAM_RE = re.compile(
    r'(?i)(\bxxx\b|sex\s*(?:tape|video|videos?)\b|'
    r'\bporn\b|\bnude\b|\bnaked\b|webcam\s*(?:sex|live)|'
    r'adult\s*content|explicit\s*(?:content|material)|'
    r'\bsexvideo\b|\bsextape\b)',
)


def _filter_url_terms(terms: list[str]) -> list[str]:
    """Remove URL-shaped strings from a term list so they are not sent to PubMed/CrossRef."""
    return [t for t in terms if not _URL_RE.match(t.strip())]


def _extract_urls_from_texts(texts: list[str]) -> list[str]:
    """Return unique, safe URLs found across a list of message texts (max _MAX_MESSAGE_URLS)."""
    seen: set[str] = set()
    out: list[str] = []
    for text in texts:
        for url in _URL_RE.findall(text):
            url = url.rstrip('.,;:!?)')
            if url not in seen and _is_safe_url(url):
                seen.add(url)
                out.append(url)
                if len(out) >= _MAX_MESSAGE_URLS:
                    return out
    return out


def _url_fetch_to_source(result: dict) -> dict:
    """Convert a fetch_url_contents result to the shape expected by _embed_and_index_sources."""
    return {
        "source_type": "url",
        "pmid": None,
        "doi": None,
        "title": result.get("title"),
        "content_for_embedding": result.get("content_for_embedding"),
        "tags": ["url", "external"],
        "abstract_source": "url",
        "url": result.get("url"),
    }


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


async def _extract_terms_from_message(text: str) -> list[str]:
    from src.nlp import extract_terms
    try:
        result = await extract_terms(text or "")
        return result
    except Exception as e:
        logger.error(f"[nlp] extract_terms failed: {type(e).__name__}: {e}")
        return []


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
    except Exception as e:
        logger.warning(f"[pubmed] esearch failed: {e}")
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

    logger.info(f"[pubmed] fetched {len(out)} articles")
    return out


async def _search_crossref_sources(client: httpx.AsyncClient, terms: list[str], max_results: int = 4) -> list[dict]:
    if not terms:
        return []

    query = " ".join(terms[:12])

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
        if _SPAM_RE.search(title):
            logger.warning(f"[crossref] skipping spam/low-quality item doi={doi}: '{title[:80]}'")
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

    logger.info(f"[crossref] fetched {len(out)} items")
    return out


_wiki = wikipediaapi.Wikipedia(
    user_agent="cancerbot/1.0 (medical-rag-assistant)",
    language="en",
    extract_format=wikipediaapi.ExtractFormat.WIKI,
)


async def _search_wikipedia_sources(terms: list[str], max_results: int = 3) -> list[dict]:
    if not terms:
        return []

    def _fetch() -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()
        for term in terms[:10]:
            if len(out) >= max_results:
                break
            try:
                page = _wiki.page(term)
                if not page.exists():
                    continue
                if page.title in seen:
                    continue
                seen.add(page.title)
                summary = (page.summary or "").strip()
                if len(summary) < 80:
                    continue
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
                logger.warning(f"[wikipedia] error for term='{term}': {e}")
                continue

        logger.info(f"[wikipedia] fetched {len(out)} pages")
        return out

    return await asyncio.to_thread(_fetch)


def _embed_and_index_sources(sources: list[dict]) -> tuple[int, int]:
    if not sources:
        return 0, 0

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
            indexed += 1
        except Exception as e:
            logger.warning(f"[index] failed to index '{source.get('title','?')[:60]}': {e}")
            skipped += 1

    return indexed, skipped


async def search_and_embed(
    conversation,
    emit: StageEmitter = _emit_noop,
) -> dict[str, Any]:
    messages = list(getattr(conversation, "messages", []) or [])

    # Get the last 4 messages
    last_messages = messages[-4:]
    # Extract text content from messages for later use
    message_texts = [str(getattr(m, "content", "") or "").strip() for m in last_messages]
    message_texts = [t for t in message_texts if t]

    await emit("analyzing_recent_messages", {"messages_considered": len(last_messages)})
    if not last_messages:
        logger.warning(f"[search_and_embed] No messages found, returning empty")
        return {
            "terms": [],
            "pubmed_found": 0,
            "crossref_found": 0,
            "indexed": 0,
            "skipped": 0,
        }

    # Collect stored terms from recent messages
    stored_terms: list[str] = []
    for msg in last_messages:
        msg_terms = getattr(msg, 'extracted_terms', None)
        if msg_terms and isinstance(msg_terms, list):
            stored_terms.extend(msg_terms)
    stored_terms = _dedupe_terms(stored_terms)

    # Use stored terms if available, otherwise extract them
    if stored_terms:
        terms = stored_terms
    else:
        await emit("extracting_search_terms", {"source": "nlp"})

        term_results = await asyncio.gather(
            *[_extract_terms_from_message(text) for text in message_texts],
            return_exceptions=True,
        )

        terms: list[str] = []
        for i, result in enumerate(term_results):
            if isinstance(result, Exception):
                logger.warning(f"[nlp] term extraction failed for message {i}: {result}")
            else:
                terms.extend(result)

        terms = _dedupe_terms(terms)

        if not terms:
            logger.warning("[nlp] no terms extracted, falling back to word extraction")
            fallback_terms = []
            for text in message_texts:
                words = text.split()
                meaningful = [w.lower().strip('?.,!;:').strip() for w in words if len(w) >= 3]
                meaningful = [w for w in meaningful if w and w.lower() not in {
                    'the', 'and', 'or', 'is', 'are', 'was', 'were', 'be', 'been',
                    'what', 'that', 'this', 'from', 'with', 'for', 'but', 'not',
                    'has', 'have', 'had', 'can', 'could', 'will', 'would', 'should',
                    'may', 'might', 'do', 'does', 'did', 'get', 'got', 'use', 'used',
                    'how', 'why', 'when', 'where', 'who', 'which', 'there', 'here',
                    'also', 'just', 'very', 'more', 'most', 'such', 'than', 'then',
                    'about', 'like', 'into', 'over', 'after', 'some', 'any', 'all',
                }]
                fallback_terms.extend(meaningful)
            terms = _dedupe_terms(fallback_terms)

    # Detect and fetch any URLs found in recent messages
    message_urls = _extract_urls_from_texts(message_texts)
    url_context_items: list[dict] = []  # raw fetch results — returned for direct context injection
    url_sources: list[dict] = []        # converted shape for indexing
    if message_urls:
        await emit("fetching_urls", {"count": len(message_urls), "urls": message_urls})
        url_context_items = await fetch_url_contents(message_urls)
        url_sources = [_url_fetch_to_source(r) for r in url_context_items]

    # Strip URL-shaped strings so they are not sent as PubMed/CrossRef/Wikipedia queries
    terms = _filter_url_terms(terms)

    await emit("terms_ready", {"terms_count": len(terms), "terms": terms[:20]})

    if not terms and not url_sources:
        logger.warning("[search_and_embed] no terms or URL sources, aborting search")
        return {
            "terms": [],
            "pubmed_found": 0,
            "crossref_found": 0,
            "wikipedia_found": 0,
            "indexed": 0,
            "skipped": 0,
        }

    # Search for sources using the terms (skip external search if only URLs were provided)
    pubmed_sources: list[dict] = []
    crossref_sources: list[dict] = []
    wikipedia_sources: list[dict] = []
    if terms:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
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
            "url_found": len(url_sources),
            "pubmed_found": len(pubmed_sources),
            "crossref_found": len(crossref_sources),
            "wikipedia_found": len(wikipedia_sources),
            "total_found": len(url_sources) + len(pubmed_sources) + len(crossref_sources) + len(wikipedia_sources),
        },
    )

    # Prepare data for external search recording (will be recorded in sync context by caller)
    original_query = message_texts[-1] if message_texts else "unknown"
    conv_id = getattr(conversation, 'id', None)
    # Get the last message (user's message that triggered the search)
    last_msg = messages[-1] if messages else None
    msg_id = getattr(last_msg, 'id', None) if last_msg else None

    logger.info(f"[search] pubmed={len(pubmed_sources)} crossref={len(crossref_sources)} wikipedia={len(wikipedia_sources)} url={len(url_sources)}")

    merged_sources = [*url_sources, *pubmed_sources, *crossref_sources, *wikipedia_sources]
    await emit("embedding_and_indexing_sources", {"total_sources": len(merged_sources)})
    indexed, skipped = await asyncio.to_thread(_embed_and_index_sources, merged_sources)
    await emit("sources_indexed", {"indexed": indexed, "skipped": skipped})
    logger.info(f"[search] indexed={indexed} skipped={skipped}")

    return {
        "terms": terms,
        "url_found": len(url_sources),
        "url_context_items": url_context_items,
        "pubmed_found": len(pubmed_sources),
        "crossref_found": len(crossref_sources),
        "wikipedia_found": len(wikipedia_sources),
        "indexed": indexed,
        "skipped": skipped,
        "external_search_data": {
            "original_query": original_query,
            "conversation_id": conv_id,
            "message_id": msg_id,
            "pubmed_sources": pubmed_sources,
            "crossref_sources": crossref_sources,
            "wikipedia_sources": wikipedia_sources,
            "extracted_terms": terms,
        },
    }


CANCER_KEYWORDS: frozenset[str] = frozenset({
    # Disease terms
    "cancer", "carcinoma", "sarcoma", "lymphoma", "leukemia", "melanoma",
    "glioma", "glioblastoma", "myeloma", "mesothelioma", "neuroblastoma",
    "blastoma", "adenocarcinoma", "squamous cell", "neoplasm", "neoplasia",
    "tumor", "tumour", "malignant", "malignancy", "metastasis", "metastatic",
    "oncology", "oncologist", "oncogene",
    # Treatment
    "chemotherapy", "radiotherapy", "immunotherapy", "targeted therapy",
    "checkpoint inhibitor", "car-t", "car t", "stem cell transplant",
    "radiation therapy", "surgery", "resection", "biopsy",
    # Molecular / pathway
    "apoptosis", "angiogenesis", "tumor suppressor", "p53", "brca", "egfr",
    "her2", "pd-l1", "pd-1", "ctla-4", "mtor", "kras", "ras", "vegf",
    "cell proliferation", "cell cycle", "dna repair", "mutation", "biomarker",
    # Specific cancer types
    "breast cancer", "lung cancer", "prostate cancer", "colon cancer",
    "colorectal cancer", "pancreatic cancer", "ovarian cancer",
    "cervical cancer", "gastric cancer", "liver cancer", "thyroid cancer",
    "kidney cancer", "bladder cancer", "brain tumor", "skin cancer",
    "blood cancer", "bone cancer", "endometrial cancer",
    # manually added terms that are highly indicative of cancer relevance
    "carcinogenesis", "tumor microenvironment", "cancer stem cell","ferroptosis", "epithelial-mesenchymal transition", 
    "ctc", "circulating tumor cell", "marker of invasiveness", "tumor heterogeneity", "liquid biopsy", "tumor mutational burden", "microsatellite instability", "cancer-associated fibroblast", "tumor-infiltrating lymphocyte", "tumor-associated macrophage", "cancer immunoediting", "tumor angiogenesis", "oncogenic driver", "tumor suppressor gene", "cancer-testis antigen", "tumor neoantigen", "cancer vaccine target", "tumor immune evasion", "cancer dormancy", "tumor progression", "cancer cachexia", "tumor lysis syndrome",

})


def _is_cancer_related(terms: list[str]) -> bool:
    """Return True if any extracted term overlaps with the cancer keyword set."""
    normalized = {t.lower().strip() for t in terms}
    if normalized & CANCER_KEYWORDS:
        return True
    # Also check if a keyword is a substring of a term (e.g. "cancer" in "cancerous")
    # Note: intentionally NOT checking `term in kw` — short NLP tokens (e.g. "as", "or")
    # are substrings of many keywords and cause false positives.
    for term in normalized:
        for kw in CANCER_KEYWORDS:
            if kw in term:
                return True
    return False


_DOI_IN_URL_RE = re.compile(r'(10\.\d{4,}/[^\s?#&"\'<>]+)', re.IGNORECASE)
_NATURE_ARTICLE_RE = re.compile(r'nature\.com/articles/(s\d[\w-]+)', re.IGNORECASE)


def _extract_doi_from_url(url: str) -> str | None:
    """Return a DOI if one can be extracted from a publisher URL, otherwise None."""
    # Generic: DOI appears verbatim in the URL path (Springer, Wiley, ACS, PLOS, BMC, …)
    m = _DOI_IN_URL_RE.search(url)
    if m:
        return m.group(1).rstrip('.')
    # Nature family: articles/s41586-026-10612-6  →  10.1038/s41586-026-10612-6
    m = _NATURE_ARTICLE_RE.search(url)
    if m:
        return f"10.1038/{m.group(1)}"
    return None


async def _resolve_doi(client: httpx.AsyncClient, doi: str) -> dict | None:
    """Return {title, abstract, doi, url} for a DOI via CrossRef, then PubMed as fallback."""
    # CrossRef direct lookup
    try:
        resp = await client.get(
            f"https://api.crossref.org/works/{quote_plus(doi)}",
            timeout=httpx.Timeout(15.0),
        )
        if resp.status_code == 200:
            item = resp.json().get("message") or {}
            title_arr = item.get("title") or []
            title = (title_arr[0] if title_arr else "").strip()
            abstract = _strip_markup(item.get("abstract"))
            if title:
                logger.info(f"[doi] CrossRef resolved doi={doi}: '{title[:80]}'")
                return {
                    "title": title,
                    "abstract": abstract,
                    "doi": doi,
                    "url": item.get("URL") or f"https://doi.org/{doi}",
                }
    except Exception as e:
        logger.warning(f"[doi] CrossRef lookup failed doi={doi}: {e}")

    # PubMed fallback — search by DOI field
    try:
        esearch_resp = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db": "pubmed", "retmode": "json", "retmax": 1, "term": f"{doi}[doi]"},
            timeout=httpx.Timeout(15.0),
        )
        esearch_resp.raise_for_status()
        id_list = (esearch_resp.json().get("esearchresult") or {}).get("idlist") or []
        if id_list:
            efetch_resp = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                params={"db": "pubmed", "id": id_list[0], "retmode": "xml"},
                timeout=httpx.Timeout(15.0),
            )
            efetch_resp.raise_for_status()
            root = ET.fromstring(efetch_resp.text)
            article_xml = root.find(".//PubmedArticle")
            if article_xml is not None:
                source = pubmed_article_xml_to_source(ET.tostring(article_xml, encoding="unicode"))
                if source.get("title"):
                    logger.info(f"[doi] PubMed resolved doi={doi}: '{source.get('title','')[:80]}'")
                    return {
                        "title": source.get("title"),
                        "abstract": source.get("abstract"),
                        "doi": doi,
                        "url": f"https://doi.org/{doi}",
                    }
    except Exception as e:
        logger.warning(f"[doi] PubMed lookup failed doi={doi}: {e}")

    return None


async def _unpaywall_oa_url(client: httpx.AsyncClient, doi: str) -> str | None:
    """Return the best open-access full-text URL for a DOI via Unpaywall, or None."""
    email = os.getenv("UNPAYWALL_EMAIL", "").strip()
    if not email:
        return None
    try:
        resp = await client.get(
            f"https://api.unpaywall.org/v2/{quote_plus(doi)}",
            params={"email": email},
            timeout=httpx.Timeout(10.0),
        )
        if resp.status_code == 200:
            best = resp.json().get("best_oa_location") or {}
            oa_url = best.get("url_for_landing_page") or best.get("url") or best.get("url_for_pdf")
            if oa_url:
                logger.info(f"[unpaywall] OA URL for doi={doi}: {oa_url}")
                return oa_url
    except Exception as e:
        logger.warning(f"[unpaywall] Failed doi={doi}: {e}")
    return None


async def fetch_url_contents(urls: list[str]) -> list[dict]:
    """Fetch text content from a list of URLs and return context-ready dicts.

    For URLs with a resolvable DOI, uses CrossRef → PubMed → Unpaywall (OA scrape)
    to get structured title + abstract without hitting paywalls.
    Falls back to plain web scraping for all other URLs.

    Each returned item shape:
        {"id": "url:<sha1>", "content_for_embedding": "<text>", "title": "...", "url": "...", "cancer_related": bool}
    """
    from bs4 import BeautifulSoup

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/35.0.1916.47 Safari/537.36"
        )
    }
    MAX_CHARS = 4000

    def _scrape_html(content: bytes, encoding: str, fallback_title: str) -> tuple[str, str]:
        html = content.decode(encoding, errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        t = soup.title.string.strip() if soup.title and soup.title.string else fallback_title
        body = " ".join(soup.get_text(separator=" ").split())[:MAX_CHARS]
        return t, body

    async def _fetch_one(client: httpx.AsyncClient, url: str) -> dict | None:
        title: str | None = None
        text: str | None = None

        # --- Path 1: DOI-based resolution (structured, paywall-free) ---
        doi = _extract_doi_from_url(url)
        if doi:
            resolved = await _resolve_doi(client, doi)
            if resolved:
                title = resolved.get("title")
                abstract = resolved.get("abstract") or ""
                if abstract:
                    text = f"{title}\n\n{abstract}" if title else abstract
                    logger.info(f"[fetch_url] DOI path succeeded for {url} ({len(text)} chars)")

            # No abstract from CrossRef/PubMed — try Unpaywall for an OA URL to scrape
            if not text:
                oa_url = await _unpaywall_oa_url(client, doi)
                if oa_url and oa_url != url:
                    try:
                        oa_resp = await client.get(oa_url, headers=HEADERS, follow_redirects=True)
                        oa_resp.raise_for_status()
                        oa_title, oa_text = await asyncio.to_thread(
                            _scrape_html, oa_resp.content, oa_resp.encoding or "utf-8", title or url
                        )
                        if oa_text:
                            title = title or oa_title
                            text = oa_text
                            logger.info(f"[fetch_url] Unpaywall OA scrape succeeded for {url} ({len(text)} chars)")
                    except Exception as e:
                        logger.warning(f"[fetch_url] OA scrape failed for {oa_url}: {e}")

        # --- Path 2: Plain web scraping fallback ---
        if not text:
            try:
                resp = await client.get(url, headers=HEADERS, follow_redirects=True)
                resp.raise_for_status()
                page_title, page_text = await asyncio.to_thread(
                    _scrape_html, resp.content, resp.encoding or "utf-8", url
                )
                title = title or page_title
                text = page_text or None
                if text:
                    logger.info(f"[fetch_url] Web scrape fallback for {url} ({len(text)} chars)")
            except Exception as e:
                logger.warning(f"[fetch_url] Failed to fetch {url}: {type(e).__name__}: {e}")

        if not text:
            return None

        terms = await _extract_terms_from_message(text)
        cancer_related = _is_cancer_related(terms)
        logger.info(f"[fetch_url] {url} — cancer_related={cancer_related}, terms={terms[:6]}")

        content = text if cancer_related else (
            f"[WARNING: This source does not appear to be cancer-related. "
            f"Use with caution.]\n{text}"
        )

        doc_id = "url:" + hashlib.sha1(url.encode("utf-8")).hexdigest()
        await asyncio.to_thread(_enqueue_url_classification, url=url, content_text=text, title=title)

        return {
            "id": doc_id,
            "content_for_embedding": content,
            "title": title or url,
            "url": url,
            "cancer_related": cancer_related,
        }

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        results = await asyncio.gather(*[_fetch_one(client, u) for u in urls])

    return [r for r in results if r is not None]


def _enqueue_url_classification(*, url: str, content_text: str, title: str | None) -> None:
    """Insert a pending classification job into the DB queue. Silently skips on error."""
    try:
        from src.db.session import SessionLocal
        from src.db.models import UrlClassificationJob
        with SessionLocal() as db:
            job = UrlClassificationJob(url=url, content_text=content_text, title=title)
            db.add(job)
            db.commit()
            logger.info(f"[url_queue] Enqueued classification job for {url}")
    except Exception as e:
        logger.warning(f"[url_queue] Failed to enqueue job for {url}: {type(e).__name__}: {e}")
