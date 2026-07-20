import asyncio
import hashlib
import html as _html
import ipaddress
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import quote_plus, urlparse
import httpx
import logging
import wikipediaapi
from bs4 import BeautifulSoup

from src.classes.ollama_connector import OllamaConnector

logger = logging.getLogger(__name__)
from src.retrieval.db_connector import dbConnector
from src.xml_to_source import pubmed_article_xml_to_source

_RETRY_MAX = 2
_RETRYABLE_HTTP = frozenset({429, 500, 502, 503, 504})
MIN_FULLTEXT_WORDS = 20


async def _retry_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    retries: int = _RETRY_MAX,
    **kwargs,
) -> httpx.Response:
    """GET with exponential backoff on transient HTTP errors and network failures."""
    delay = 1.0
    last_exc: Exception | None = None
    resp: httpx.Response | None = None
    for attempt in range(retries):
        try:
            resp = await client.get(url, **kwargs)
            if resp.status_code in _RETRYABLE_HTTP and attempt < retries - 1:
                logger.warning("[http] %s status=%d, retry %d/%d", url[:80], resp.status_code, attempt + 1, retries)
                await asyncio.sleep(delay + random.uniform(0, 0.5))
                delay *= 2
                continue
            return resp
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                logger.warning("[http] %s %s, retry %d/%d", url[:80], exc, attempt + 1, retries)
                await asyncio.sleep(delay + random.uniform(0, 0.5))
                delay *= 2
    if last_exc:
        raise last_exc
    return resp  # type: ignore[return-value]

StageEmitter = Callable[[str, Dict[str, Any]], Awaitable[None]]


def _chunk_text(text: str, max_words: int = 150, overlap: int = 40) -> list[str]:
    """Split text into overlapping word-window chunks."""
    words = text.split()
    if len(words) <= max_words:
        return [text]
    chunks = []
    step = max_words - overlap
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + max_words])
        chunks.append(chunk)
        if start + max_words >= len(words):
            break
    return chunks

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


# Stop words that must never be used as search terms even if NLP mis-tags them.
# Mirrors STOP_ENTS in nlp_service/app.py plus the fallback extraction stop list.
_TERM_STOP_WORDS: frozenset[str] = frozenset({
    # Common English function words / fallback stop list
    'the', 'and', 'or', 'is', 'are', 'was', 'were', 'be', 'been',
    'what', 'that', 'this', 'from', 'with', 'for', 'but', 'not',
    'has', 'have', 'had', 'can', 'could', 'will', 'would', 'should',
    'may', 'might', 'do', 'does', 'did', 'get', 'got', 'use', 'used',
    'how', 'why', 'when', 'where', 'who', 'which', 'there', 'here',
    'also', 'just', 'very', 'more', 'most', 'such', 'than', 'then',
    'about', 'like', 'into', 'over', 'after', 'some', 'any', 'all',
    # Request / imperative verbs (NLP STOP_ENTS)
    'tell', 'give', 'show', 'explain', 'describe', 'list', 'find',
    'know', 'need', 'want', 'help', 'make', 'look', 'take',
    'see', 'say', 'let', 'put', 'ask',
    # Other frequent false positives
    'no', 'yes', 'not', 'also', 'just',
})


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


def _clean_crossref_text(raw: Optional[str]) -> Optional[str]:
    """Parse CrossRef's JATS/HTML-tagged title or abstract into clean, readable text.

    CrossRef abstracts are wrapped in JATS tags, e.g.
    "<jats:title>Abstract</jats:title><jats:p>...</jats:p>". A blunt tag-strip
    leaves the redundant "Abstract" label as a literal prefix in the output, so
    this drops <jats:title>/<title> elements whose text is just that generic
    label while keeping meaningful structured-abstract headers (Background,
    Methods, Results, ...). Titles carry simpler inline markup (e.g. "<i>gene</i>"
    for italicized gene names), which falls through to the blunt-strip fallback.
    """
    if not raw:
        return None
    try:
        soup = BeautifulSoup(raw, "html.parser")
        parts: list[str] = []
        for el in soup.find_all(["jats:title", "title", "jats:p", "p"]):
            text = el.get_text(" ", strip=True)
            if not text:
                continue
            if el.name in ("jats:title", "title") and text.lower() == "abstract":
                continue
            parts.append(text)
        cleaned = " ".join(" ".join(parts).split()).strip()
        if cleaned:
            return cleaned
    except Exception:
        pass
    # Fallback: blunt tag strip (handles malformed/unexpected markup)
    cleaned = re.sub(r"<[^>]+>", " ", raw)
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
    logger.info("[conversation_helper] _extract_terms_from_message input: %r", (text or "")[:200])
    try:
        result = await extract_terms(text or "")
        logger.info("[conversation_helper] _extract_terms_from_message output: %s", result)
        return result
    except Exception as e:
        logger.error(f"[nlp] extract_terms failed: {type(e).__name__}: {e}")
        return []


async def _extract_term_groups_from_message(text: str) -> tuple[list[str], list[dict]]:
    from src.nlp import extract_with_groups
    logger.info("[conversation_helper] _extract_term_groups_from_message input: %r", (text or "")[:200])
    try:
        terms, groups = await extract_with_groups(text or "")
        logger.info("[conversation_helper] _extract_term_groups_from_message output: terms=%s groups=%s", terms, groups)
        return terms, groups
    except Exception as e:
        logger.error(f"[nlp] extract_with_groups failed: {type(e).__name__}: {e}")
        return [], []


def _merge_entity_groups(groups_per_message: list[list[dict]]) -> list[dict]:
    """Merge entity groups from multiple messages, deduping by term (case-insensitive)."""
    merged: dict[str, dict] = {}
    for groups in groups_per_message:
        for g in groups:
            term = (g.get("term") or "").strip()
            if not term:
                continue
            key = term.lower()
            if key not in merged:
                merged[key] = {"term": term, "synonyms": list(g.get("synonyms") or [])}
            else:
                existing_syn = {s.lower() for s in merged[key]["synonyms"]}
                for s in g.get("synonyms") or []:
                    if s.lower() not in existing_syn:
                        merged[key]["synonyms"].append(s)
                        existing_syn.add(s.lower())
    return list(merged.values())


def _representative_terms(entity_groups: list[dict], fallback_terms: list[str]) -> list[str]:
    """One term per distinct entity (its own name, not its synonyms).

    Used for search APIs that rank by free-text relevance rather than boolean
    logic (CrossRef, Wikipedia) — feeding them the fully expanded synonym list
    lets a heavily-synonymed entity (e.g. 5 GBM synonyms) dominate the query
    and drown out a single-term entity (e.g. one drug name) in ranking.
    """
    if not entity_groups:
        return fallback_terms
    return [g["term"] for g in entity_groups if g.get("term")]


async def _pubmed_esearch(client: httpx.AsyncClient, search_query: str, max_results: int) -> list[str]:
    esearch_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&retmode=json&retmax={max_results}&sort=relevance&term={quote_plus(search_query)}"
    )
    esearch_resp = await _retry_get(client, esearch_url)
    esearch_resp.raise_for_status()
    return (esearch_resp.json().get("esearchresult") or {}).get("idlist") or []


async def _search_pubmed_sources(
    client: httpx.AsyncClient,
    terms: list[str],
    max_results: int = 4,
    entity_groups: list[dict] | None = None,
) -> list[dict]:
    if not terms:
        return []

    flat_query = " OR ".join(f"({t})" for t in terms[:12])

    # When we know which terms belong to which distinct entity (e.g. a drug vs
    # a disease), require at least one synonym from each group to co-occur —
    # otherwise a heavily-synonymed entity's OR-matches swamp the results and
    # papers combining both entities never make it into max_results.
    and_query = None
    if entity_groups and len(entity_groups) >= 2:
        clauses = []
        for g in entity_groups[:6]:
            group_terms = [g["term"], *g.get("synonyms", [])]
            clause = " OR ".join(f"({t})" for t in group_terms)
            clauses.append(f"({clause})")
        and_query = " AND ".join(clauses)

    try:
        id_list: list[str] = []
        if and_query:
            id_list = await _pubmed_esearch(client, and_query, max_results)
            if not id_list:
                logger.info("[pubmed] AND-grouped query returned nothing, falling back to flat OR query")
        if not id_list:
            id_list = await _pubmed_esearch(client, flat_query, max_results)
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
        efetch_resp = await _retry_get(client, efetch_url)
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


async def _search_crossref_sources(
    client: httpx.AsyncClient,
    terms: list[str],
    max_results: int = 4,
    entity_groups: list[dict] | None = None,
) -> list[dict]:
    if not terms:
        return []

    # CrossRef's bibliographic search ranks by free-text relevance, not boolean
    # logic — feeding it the fully synonym-expanded term list lets a
    # heavily-synonymed entity dominate the query, so use one representative
    # term per distinct entity when we know the grouping.
    query = " ".join(_representative_terms(entity_groups, terms)[:12])

    url = "https://api.crossref.org/works"
    params = {
        "query.bibliographic": query,
        "rows": max_results,
        "select": "DOI,title,abstract,URL",
        "filter": "has-abstract:true",
    }
    try:
        resp = await _retry_get(client, url, params=params)
        resp.raise_for_status()
        items = (resp.json().get("message") or {}).get("items") or []
    except Exception as e:
        logger.warning(f"[crossref] request failed: {e}")
        return []

    out: list[dict] = []
    for item in items:
        doi = (item.get("DOI") or "").strip()
        title_arr = item.get("title") or []
        raw_title = (title_arr[0] if isinstance(title_arr, list) and title_arr else "") or ""
        title = _clean_crossref_text(raw_title) or raw_title.strip()
        abstract = _clean_crossref_text(item.get("abstract"))
        if not abstract:
            logger.debug(f"[crossref] skipping doi={doi} — no usable abstract after cleaning")
            continue
        content_for_embedding = f"{title}\n\n{abstract}".strip()
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

    async def _supplement_with_oa_fulltext(entry: dict) -> None:
        doi = entry.get("doi")
        if not doi:
            return
        remaining = MAX_FULLTEXT_WORDS - len(entry["content_for_embedding"].split())
        if remaining <= 0:
            return
        excerpt = await _fetch_oa_fulltext_excerpt(client, doi, entry.get("url"), remaining)
        if excerpt:
            entry["content_for_embedding"] = f"{entry['content_for_embedding']}\n\n{excerpt}".strip()

    await asyncio.gather(*[_supplement_with_oa_fulltext(entry) for entry in out])

    logger.info(f"[crossref] fetched {len(out)} items")
    return out


_WIKI_USER_AGENT = (
    "cancerbot/1.0 (medical-rag-assistant; "
    + os.getenv("EMAIL_FROM", "contact@cancerbot.app")
    + ")"
)

_wiki = wikipediaapi.Wikipedia(
    user_agent=_WIKI_USER_AGENT,
    language="en",
    extract_format=wikipediaapi.ExtractFormat.WIKI,
)

_WIKI_SEARCH_URL = "https://en.wikipedia.org/w/api.php"


def _strip_wiki_html(s: str) -> str:
    return _html.unescape(re.sub(r'<[^>]+>', '', s))


def _pick_oncology_title(candidates: list[dict]) -> str | None:
    """Return the title most relevant to oncology from Wikipedia search results."""
    for item in candidates:
        title = item.get("title") or ""
        snippet = _strip_wiki_html(item.get("snippet") or "")
        combined = title.lower() + " " + snippet.lower()
        if title and any(kw in combined for kw in CANCER_KEYWORDS):
            return title
    # Fall back to highest-ranked result that has a title
    for item in candidates:
        title = item.get("title")
        if title:
            return title
    return None


def _wiki_search(term: str, limit: int = 5) -> list[dict]:
    """Call Wikipedia's search API and return result items."""
    delay = 1.0
    for attempt in range(_RETRY_MAX):
        try:
            resp = httpx.get(
                _WIKI_SEARCH_URL,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": term,
                    "srlimit": limit,
                    "format": "json",
                    "utf8": 1,
                },
                headers={"User-Agent": _WIKI_USER_AGENT},
                timeout=8,
            )
            if resp.status_code in _RETRYABLE_HTTP and attempt < _RETRY_MAX - 1:
                logger.warning("[wikipedia] search status=%d for term='%s', retry %d/%d", resp.status_code, term, attempt + 1, _RETRY_MAX)
                time.sleep(delay + random.uniform(0, 0.5))
                delay *= 2
                continue
            resp.raise_for_status()
            return resp.json().get("query", {}).get("search", [])
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as exc:
            if attempt < _RETRY_MAX - 1:
                logger.warning("[wikipedia] search transient error for term='%s', retry %d/%d: %s", term, attempt + 1, _RETRY_MAX, exc)
                time.sleep(delay + random.uniform(0, 0.5))
                delay *= 2
            else:
                logger.warning("[wikipedia] search API error for term='%s': %s", term, exc)
                return []
        except Exception as e:
            logger.warning("[wikipedia] search API error for term='%s': %s", term, e)
            return []
    return []


async def _search_wikipedia_sources(
    terms: list[str],
    max_results: int = 3,
    entity_groups: list[dict] | None = None,
) -> list[dict]:
    if not terms:
        return []

    def _fetch() -> list[dict]:
        # Each term gets its own independent page lookup, so a flat list where
        # one entity's synonyms dominate wastes lookups on near-duplicate
        # pages instead of covering distinct entities in the message.
        batch = _representative_terms(entity_groups, terms)[:10]
        out: list[dict] = []
        seen: set[str] = set()
        for term in batch:
            if len(out) >= max_results:
                break
            try:
                candidates = _wiki_search(term)
                title = _pick_oncology_title(candidates) if candidates else term
                page = _wiki.page(title)
                if not page.exists():
                    page = _wiki.page(term)
                    if not page.exists():
                        continue
                if page.title in seen:
                    continue
                seen.add(page.title)
                summary = (page.summary or "").strip()
                if len(summary.split()) < MIN_FULLTEXT_WORDS:
                    continue
                out.append(
                    {
                        "source_type": "wikipedia",
                        "pmid": None,
                        "doi": None,
                        "title": page.title,
                        "content_for_embedding": f"{page.title}\n\n{summary}",
                        "abstract_source": "wikipedia",
                        "url": page.fullurl,
                    }
                )
            except Exception as e:
                logger.warning(f"[wikipedia] error for term='{term}': {e}")
                continue

        logger.info("[wikipedia] fetched %d pages", len(out))
        return out

    return await asyncio.to_thread(_fetch)


def _embed_and_index_sources(sources: list[dict], terms: list[str] | None = None) -> tuple[int, int]:
    if not sources:
        return 0, 0

    db = dbConnector()
    db.create_index("sources_index")
    indexed = 0
    skipped = 0
    clean_terms = [t.strip() for t in (terms or []) if t and len(t.strip()) >= 2]

    # Assign stable base IDs and deduplicate within the batch
    candidate: list[tuple[str, dict]] = []
    seen_base_ids: set[str] = set()
    for source in sources:
        content = (source.get("content_for_embedding") or "").strip()
        if len(content.split()) < MIN_FULLTEXT_WORDS:
            logger.debug(f"[index] skipping source '{source.get('title','?')[:60]}' — content too short")
            skipped += 1
            continue
        base_id = _stable_source_id(source)
        if base_id in seen_base_ids:
            logger.debug(f"[index] skipping duplicate base_id={base_id}")
            skipped += 1
            continue
        seen_base_ids.add(base_id)
        candidate.append((base_id, source))

    # Check which base IDs are already indexed (any chunk present)
    candidate_ids = [bid for bid, _ in candidate]
    already_indexed = db.existing_base_source_ids(candidate_ids)
    new_ids = [bid for bid in candidate_ids if bid not in already_indexed]
    logger.info(
        "[index] candidates=%d already_indexed=%d to_index=%d — already_indexed=%s",
        len(candidate_ids), len(already_indexed), len(new_ids), sorted(already_indexed),
    )

    for base_id, source in candidate:
        if base_id in already_indexed:
            logger.info("[index] skip %s (already indexed)", base_id)
            skipped += 1
            continue
        full_text = (source.get("content_for_embedding") or "").strip()
        full_text_word_count = len(full_text.split())
        chunks = _chunk_text(full_text)
        logger.info("[index] indexing %s — %d chunk(s)", base_id, len(chunks))

        for chunk_index, chunk_text in enumerate(chunks):
            try:
                doc = {
                    "id": f"{base_id}:c{chunk_index}",
                    "source_id": base_id,
                    "chunk_index": chunk_index,
                    "source_type": source.get("source_type") or "source",
                    "pmid": source.get("pmid"),
                    "doi": source.get("doi"),
                    "title": source.get("title"),
                    "full_text": full_text,
                    "full_text_word_count": full_text_word_count,
                    "content_for_embedding": chunk_text,
                    "tags": clean_terms,
                    "abstract_source": source.get("abstract_source") or source.get("source_type"),
                    "url": source.get("url"),
                    "embedding": OllamaConnector.embed_text(chunk_text),
                }
                db.index_to_db("sources_index", doc)
                logger.info("[index] indexed %s:c%d", base_id, chunk_index)
                indexed += 1
            except Exception as e:
                logger.warning(f"[index] failed to index '{source.get('title','?')[:60]}' chunk={chunk_index}: {e}")
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

    # Older messages in context can reuse their own cached extracted_terms
    # (set back when each was originally processed) to avoid re-calling the
    # NLP service. The *current* message is always freshly extracted here —
    # conversations.py already saves a flat extracted_terms cache on it
    # before search_and_embed runs, and reusing that cache would skip
    # entity_groups entirely, since it has no per-entity synonym grouping
    # preserved. entity_groups matters most for the message the user is
    # actually asking about right now, so it can't be skipped.
    history_messages = last_messages[:-1]
    latest_text = message_texts[-1] if message_texts else None

    history_stored_terms: list[str] = []
    for msg in history_messages:
        msg_terms = getattr(msg, 'extracted_terms', None)
        if msg_terms and isinstance(msg_terms, list):
            history_stored_terms.extend(msg_terms)
    history_stored_terms = [t for t in _dedupe_terms(history_stored_terms) if t.lower() not in _TERM_STOP_WORDS]

    entity_groups: list[dict] = []
    if latest_text:
        await emit("extracting_search_terms", {"source": "nlp"})
        latest_terms, latest_groups = await _extract_term_groups_from_message(latest_text)
        entity_groups = _merge_entity_groups([latest_groups])
    else:
        latest_terms = []

    terms = _dedupe_terms([*history_stored_terms, *latest_terms])

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
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as client:
            await emit("searching_pubmed", {"limit": 4})
            await emit("searching_crossref", {"limit": 4})
            await emit("searching_wikipedia", {"limit": 3})
            pubmed_sources, crossref_sources, wikipedia_sources = await asyncio.gather(
                asyncio.create_task(_search_pubmed_sources(client, terms, max_results=4, entity_groups=entity_groups)),
                asyncio.create_task(_search_crossref_sources(client, terms, max_results=4, entity_groups=entity_groups)),
                _search_wikipedia_sources(terms, max_results=3, entity_groups=entity_groups),
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
    indexed, skipped = await asyncio.to_thread(_embed_and_index_sources, merged_sources, terms)
    await emit("sources_indexed", {"indexed": indexed, "skipped": skipped})
    logger.info(f"[search] indexed={indexed} skipped={skipped}")

    return {
        "terms": terms,
        "entity_groups": entity_groups,
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
    "onco", "oncology", "oncologist", "oncogene",
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
_PUBMED_PMID_RE = re.compile(r'(?:pubmed\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pubmed)/(\d+)', re.IGNORECASE)


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


def _extract_pmid_from_url(url: str) -> str | None:
    """Return a PubMed ID if the URL points to a PubMed article page."""
    m = _PUBMED_PMID_RE.search(url)
    return m.group(1) if m else None


async def _fetch_pubmed_by_pmid(client: httpx.AsyncClient, pmid: str) -> dict | None:
    """Fetch a PubMed article by PMID and return a source dict."""
    try:
        resp = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={"db": "pubmed", "id": pmid, "retmode": "xml"},
            timeout=httpx.Timeout(15.0),
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        article_xml = root.find(".//PubmedArticle")
        if article_xml is not None:
            return pubmed_article_xml_to_source(ET.tostring(article_xml, encoding="unicode"))
    except Exception as e:
        logger.warning(f"[fetch_url] PubMed PMID fetch failed pmid={pmid}: {e}")
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
            raw_title = (title_arr[0] if title_arr else "").strip()
            title = _clean_crossref_text(raw_title) or raw_title
            abstract = _clean_crossref_text(item.get("abstract"))
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


_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/35.0.1916.47 Safari/537.36"
    )
}
_URL_FETCH_MAX_CHARS = 4000
MAX_FULLTEXT_WORDS = 500


def _scrape_html(content: bytes, encoding: str, fallback_title: str) -> tuple[str, str]:
    html = content.decode(encoding, errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    t = soup.title.string.strip() if soup.title and soup.title.string else fallback_title
    body = " ".join(soup.get_text(separator=" ").split())[:_URL_FETCH_MAX_CHARS]
    return t, body


async def _fetch_oa_fulltext_excerpt(
    client: httpx.AsyncClient, doi: str, exclude_url: Optional[str], max_words: int
) -> Optional[str]:
    """Best-effort open-access full-text excerpt for a DOI via Unpaywall, capped at max_words words."""
    if max_words <= 0:
        return None
    oa_url = await _unpaywall_oa_url(client, doi)
    if not oa_url or oa_url == exclude_url:
        return None
    try:
        resp = await client.get(oa_url, headers=_SCRAPE_HEADERS, follow_redirects=True, timeout=httpx.Timeout(15.0))
        resp.raise_for_status()
        _, text = await asyncio.to_thread(_scrape_html, resp.content, resp.encoding or "utf-8", "")
        if text:
            excerpt = " ".join(text.split()[:max_words])
            if excerpt:
                logger.info(f"[oa-fulltext] doi={doi} excerpt {len(excerpt.split())} words from {oa_url}")
                return excerpt
    except Exception as e:
        logger.warning(f"[oa-fulltext] scrape failed doi={doi} url={oa_url}: {e}")
    return None


async def fetch_url_contents(urls: list[str]) -> list[dict]:
    """Fetch text content from a list of URLs and return context-ready dicts.

    For URLs with a resolvable DOI, uses CrossRef → PubMed → Unpaywall (OA scrape)
    to get structured title + abstract without hitting paywalls.
    Falls back to plain web scraping for all other URLs.

    Each returned item shape:
        {"id": "url:<sha1>", "content_for_embedding": "<text>", "title": "...", "url": "...", "cancer_related": bool}
    """

    async def _fetch_one(client: httpx.AsyncClient, url: str) -> dict | None:
        title: str | None = None
        text: str | None = None
        pmid: str | None = None
        doi: str | None = None

        # --- Path 0: PubMed URL — extract PMID and fetch structured abstract ---
        pmid = _extract_pmid_from_url(url)
        if pmid:
            source = await _fetch_pubmed_by_pmid(client, pmid)
            if source:
                title = source.get("title")
                abstract = source.get("abstract") or ""
                doi = source.get("doi")
                if abstract:
                    text = f"{title}\n\n{abstract}" if title else abstract
                    logger.info(f"[fetch_url] PMID path succeeded for {url} pmid={pmid} ({len(text)} chars)")

        # --- Path 1: DOI-based resolution (structured, paywall-free) ---
        if not text:
            doi = doi or _extract_doi_from_url(url)
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
                            oa_resp = await client.get(oa_url, headers=_SCRAPE_HEADERS, follow_redirects=True)
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
                resp = await client.get(url, headers=_SCRAPE_HEADERS, follow_redirects=True)
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

        # Prefer stable structured IDs: pmid > doi > url hash
        if pmid:
            doc_id = f"pmid:{pmid}"
        elif doi:
            doc_id = f"doi:{doi}"
        else:
            doc_id = "url:" + hashlib.sha1(url.encode("utf-8")).hexdigest()

        await asyncio.to_thread(_enqueue_url_classification, url=url, content_text=text, title=title)

        return {
            "id": doc_id,
            "pmid": pmid,
            "doi": doi,
            "source_type": "pubmed" if pmid else ("crossref" if doi else "url"),
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
