import logging
import os

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_NLP_URL = os.getenv("NLP_SERVICE_URL", "http://localhost:8100")
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=_NLP_URL, timeout=10.0)
    return _client


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
