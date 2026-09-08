import logging
import os

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_NLP_URL = os.getenv("NLP_SERVICE_URL", "http://localhost:8100")
_client: httpx.AsyncClient | None = None
_sync_client: httpx.Client | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=_NLP_URL, timeout=10.0)
    return _client


def _get_sync_client() -> httpx.Client:
    # run_retrieval (src/retrieval/__init__.py) is sync and runs via
    # asyncio.to_thread — no event loop to await the async client on — so
    # rerank() gets its own sync client rather than sharing _client above.
    global _sync_client
    if _sync_client is None:
        _sync_client = httpx.Client(base_url=_NLP_URL, timeout=10.0)
    return _sync_client


def load_models() -> None:
    logger.info("[nlp] Using remote NLP service at %s", _NLP_URL)


async def extract_with_groups(text: str) -> tuple[list[str], list[dict]]:
    """Return (flat_terms, entity_groups) from one call to the NLP service.

    flat_terms is the same merged entities+synonyms list extract_terms() has
    always returned. entity_groups is [{"term": ..., "synonyms": [...]}] —
    each original entity paired with its own synonyms, so callers that need
    to build a query requiring several distinct entities together (e.g. a
    drug AND a disease) aren't stuck with one flat bag of terms where a
    heavily-synonymed entity drowns out the others.
    """
    if not text:
        return [], []
    logger.info("[nlp] extract_with_groups input: %r", text[:200])
    try:
        resp = await _get_client().post("/extract", json={"text": text})
        resp.raise_for_status()
        data = resp.json()
        logger.info("[nlp] extract_with_groups raw response: %s", data)
        base = data.get("expanded_entities") or data.get("entities") or []
        synonyms = data.get("synonyms") or []
        seen: set[str] = set()
        merged: list[str] = []
        for t in (*base, *synonyms):
            key = t.lower()
            if key not in seen:
                seen.add(key)
                merged.append(t)
        groups = data.get("entity_groups") or []
        logger.info("[nlp] extract_with_groups output: terms=%s groups=%s", merged, groups)
        return merged, groups
    except Exception as e:
        logger.error("[nlp] extract_with_groups failed: %s: %s", type(e).__name__, e)
        return [], []


async def extract_terms(text: str) -> list[str]:
    terms, _ = await extract_with_groups(text)
    return terms


def rerank(query: str, documents: list[str]) -> list[float] | None:
    """Cross-encoder relevance scores for (query, document) pairs, same order
    as `documents`. Returns None on any failure (service down, timeout, bad
    response) — callers must fail open and keep their existing order rather
    than propagate, same contract as extract_with_groups/correct_spelling."""
    if not query or not documents:
        return None
    try:
        resp = _get_sync_client().post("/rerank", json={"query": query, "documents": documents})
        resp.raise_for_status()
        scores = resp.json().get("scores")
        if not isinstance(scores, list) or len(scores) != len(documents):
            logger.error("[nlp] rerank returned malformed scores: %r", scores)
            return None
        return scores
    except Exception as e:
        logger.error("[nlp] rerank failed: %s: %s", type(e).__name__, e)
        return None


async def correct_spelling(text: str) -> str:
    text = " ".join((text or "").split()).strip()
    if not text:
        return text
    try:
        resp = await _get_client().post("/spelling/correct", json={"text": text})
        resp.raise_for_status()
        return resp.json().get("corrected") or text
    except Exception as e:
        logger.error("[nlp] correct_spelling failed: %s: %s", type(e).__name__, e)
        return text
