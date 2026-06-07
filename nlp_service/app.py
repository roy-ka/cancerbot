import os
import asyncio
from contextlib import asynccontextmanager
from typing import Optional
import re
import logging
import time

from fastapi import FastAPI, Depends
from pydantic import BaseModel
from dotenv import load_dotenv
import spacy
import scispacy  # required to register scispaCy pipeline components
import scispacy.abbreviation  # registers abbreviation_detector factory
from spellchecker import SpellChecker

from sqlalchemy import select, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from models import Abbreviation, Base
from db import get_session, SessionLocal, engine

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("[NLP app] Module loading started")
load_dotenv()
logger.info("[NLP app] .env loaded")
# --- DB (SQLAlchemy) ---
DATABASE_URL = os.getenv("NLP_DATABASE_URL")
    

DATABASE_ENABLED = False  # Disabled for now due to table migration issues


# In-memory cache: short_lower -> long
abbrev_cache: dict[str, str] = {}
_abbrev_cache_lock = asyncio.Lock()
_abbrev_refresher_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _abbrev_refresher_task

    logger.info("[lifespan] Starting up...")
    logger.info(f"[lifespan] DATABASE_ENABLED={DATABASE_ENABLED}, DATABASE_URL={os.getenv('NLP_DATABASE_URL', 'NOT SET')[:50]}")

    if DATABASE_ENABLED:
        logger.info("[lifespan] Skipping abbreviation cache on startup - will load on first request")

    logger.info("[lifespan] Startup complete, yielding control")
    try:
        yield
    finally:
        logger.info("[lifespan] Shutting down...")
        if _abbrev_refresher_task:
            _abbrev_refresher_task.cancel()
            try:
                await _abbrev_refresher_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Cancerbot NLP Service", lifespan=lifespan)


async def load_abbrev_cache() -> int:
    """Load all abbreviations from DB into memory. Returns number of entries."""
    # TODO: Temporarily disabled due to table creation issues
    # Will be re-enabled once database schema is properly migrated
    logger.debug("[load_abbrev_cache] Database disabled, skipping load")
    return 0


async def get_abbrev_long(short: str) -> Optional[str]:
    """Fast lookup from in-memory cache."""
    key = (short or "").strip().lower()
    if not key:
        return None
    async with _abbrev_cache_lock:
        return abbrev_cache.get(key)


async def save_new_abbreviations(abbr_found: dict[str, str]) -> int:
    """Persist newly discovered abbreviations and refresh in-memory cache entries."""
    logger.debug(f"[save_new_abbreviations] Called with {len(abbr_found)} abbreviations")
    if not DATABASE_ENABLED or not abbr_found:
        logger.debug(f"[save_new_abbreviations] Skipping: DATABASE_ENABLED={DATABASE_ENABLED}, abbr_found={bool(abbr_found)}")
        return 0

    to_insert: list[tuple[str, str, str]] = []
    for short_raw, long_raw in abbr_found.items():
        short = (short_raw or "").strip()
        long = (long_raw or "").strip()
        key = short.lower()
        if not short or not long:
            continue
        if await get_abbrev_long(key):
            logger.debug(f"[save_new_abbreviations] Already cached: {short}")
            continue
        to_insert.append((short, long, key))

    if not to_insert:
        logger.debug(f"[save_new_abbreviations] No new abbreviations to insert")
        return 0

    logger.info(f"[save_new_abbreviations] Inserting {len(to_insert)} new abbreviations")
    saved = 0
    async with SessionLocal() as session:
        for short, long, key in to_insert:
            if await session.get(Abbreviation, short):
                logger.debug(f"[save_new_abbreviations] Skipping duplicate: {short}")
                continue
            session.add(
                Abbreviation(
                    short=short,
                    long=long,
                    source="scispacy",
                    confidence=0.85,
                )
            )
            async with _abbrev_cache_lock:
                abbrev_cache[key] = long
            saved += 1

        if saved:
            try:
                await session.commit()
                logger.info(f"[save_new_abbreviations] Saved {saved} abbreviations to DB")
            except IntegrityError as e:
                logger.error(f"[save_new_abbreviations] IntegrityError while saving: {e}")
                await session.rollback()
                return 0

    return saved


def start_abbrev_cache_refresher(interval_seconds: int = 60) -> Optional[asyncio.Task]:
    """Background task refresher (async)."""
    if not DATABASE_ENABLED:
        return None

    async def _run():
        while True:
            try:
                await load_abbrev_cache()
            except Exception as e:
                # Don't crash the service if DB hiccups
                logger.error(f"[abbrev_cache_refresher] Refresh failed: {e}", exc_info=True)
            await asyncio.sleep(max(5, interval_seconds))

    return asyncio.create_task(_run())
# Load once on startup (important for speed)
logger.info("[startup] Loading spacy model 'en_core_sci_sm'...")
nlp = spacy.load("en_core_sci_sm")
logger.info(f"[startup] Spacy model loaded. Pipeline: {nlp.pipe_names}")

# Explicitly add scispaCy abbreviation detector
if "abbreviation_detector" not in nlp.pipe_names:
    logger.info("[startup] Adding abbreviation_detector to pipeline")
    nlp.add_pipe("abbreviation_detector", last=True)
else:
    logger.info("[startup] abbreviation_detector already in pipeline")

logger.info("[startup] Loading SpellChecker...")
spell_checker = SpellChecker(distance=1)
logger.info("[startup] SpellChecker loaded")

STOP_ENTS = {"cancer", "tumor"}  # optional: cut overly generic entities


class ExtractReq(BaseModel):
    text: str


class SpellingReq(BaseModel):
    text: str


def _dedupe_keep_order(items):
    seen = set()
    out = []
    for x in items:
        k = (x or "").strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def _preserve_case(original: str, corrected: str) -> str:
    if original.isupper():
        return corrected.upper()
    if original[:1].isupper():
        return corrected.capitalize()
    return corrected


async def _correct_spelling_text(text: str) -> tuple[str, list[dict]]:
    logger.debug(f"[_correct_spelling_text] Processing text of length {len(text)}")
    doc = await run_in_threadpool(nlp, text)
    logger.debug(f"[_correct_spelling_text] NLP processed, found {len(doc.ents)} entities, {len(doc._.abbreviations)} abbreviations")

    protected_terms = {
        tok.text.strip().lower()
        for ent in doc.ents
        for tok in ent
        if tok.text and tok.text.strip()
    }
    protected_terms.update(
        {
            str(a).strip().lower()
            for a in doc._.abbreviations
            if str(a).strip()
        }
    )
    protected_terms.update(
        {
            str(a._.long_form).strip().lower()
            for a in doc._.abbreviations
            if str(a._.long_form).strip()
        }
    )
    async with _abbrev_cache_lock:
        protected_terms.update(abbrev_cache.keys())

    logger.debug(f"[_correct_spelling_text] Protected {len(protected_terms)} terms")

    parts: list[str] = []
    changes: list[dict] = []
    for tok in doc:
        raw = tok.text
        fixed = raw
        lower = raw.lower()

        should_try = (
            tok.is_alpha
            and len(raw) >= 4
            and not raw.isupper()
            and lower not in protected_terms
            and not re.search(r"\d", raw)
            and "'" not in raw
        )

        if should_try and spell_checker.unknown([lower]):
            suggestion = spell_checker.correction(lower)
            if (
                suggestion
                and suggestion != lower
                and suggestion[0] == lower[0]
                and abs(len(suggestion) - len(lower)) <= 2
            ):
                fixed = _preserve_case(raw, suggestion)
                changes.append({"from": raw, "to": fixed})
                logger.debug(f"[_correct_spelling_text] Corrected: {raw} -> {fixed}")

        parts.append(f"{fixed}{tok.whitespace_}")

    logger.debug(f"[_correct_spelling_text] Made {len(changes)} corrections")
    return "".join(parts), changes


@app.post("/spelling/correct")
async def spelling_correct(req: SpellingReq):
    start_time = time.time()
    logger.info(f"[spelling/correct] Input text length: {len(req.text or '')}")
    try:
        corrected, changes = await _correct_spelling_text(req.text or "")
        elapsed = time.time() - start_time
        logger.info(f"[spelling/correct] Processed in {elapsed:.3f}s, {len(changes)} changes made")
        return {
            "text": req.text,
            "corrected": corrected,
            "changes": changes,
        }
    except Exception as e:
        logger.error(f"[spelling/correct] Error: {e}", exc_info=True)
        raise


@app.post("/extract")
async def extract(req: ExtractReq):
    start_time = time.time()
    text_len = len(req.text or '')
    logger.info(f"[extract] Starting extraction for text length: {text_len}")

    try:
        doc = await run_in_threadpool(nlp, req.text)
        logger.debug(f"[extract] NLP processing complete, found {len(doc.ents)} raw entities")

        entities = [ent.text.strip() for ent in doc.ents if ent.text.strip()]
        logger.debug(f"[extract] After filtering empty: {len(entities)} entities")

        entities = [e for e in entities if e.lower() not in STOP_ENTS]
        logger.debug(f"[extract] After filtering stop entities: {len(entities)} entities: {entities[:5]}")

        # Abbreviations detected from text forms like "glioblastoma (GBM)"
        abbr_found = {str(a): str(a._.long_form) for a in doc._.abbreviations}
        logger.info(f"[extract] Found {len(abbr_found)} abbreviations: {abbr_found}")

        saved_abbreviations = 0
        try:
            saved_abbreviations = await save_new_abbreviations(abbr_found)
            logger.info(f"[extract] Saved {saved_abbreviations} new abbreviations to DB")
        except Exception as e:
            # Extraction should still succeed even if DB write fails.
            logger.warning(f"[extract] Save abbreviations failed: {e}", exc_info=True)

        # Expand entities using: detected abbreviations first, then DB-backed cache
        expanded = []
        for e in entities:
            key = e.lower()
            if key in abbr_found:
                expanded.append(abbr_found[key])
            else:
                expanded.append((await get_abbrev_long(key)) or e)

        result = {
            "entities": _dedupe_keep_order(entities),
            "expanded_entities": _dedupe_keep_order(expanded),
            "abbreviations_found": abbr_found,
            "saved_abbreviations": saved_abbreviations,
        }

        elapsed = time.time() - start_time
        logger.info(f"[extract] Complete in {elapsed:.3f}s - {len(result['entities'])} entities, {len(result['expanded_entities'])} expanded")

        return result
    except Exception as e:
        logger.error(f"[extract] Error: {e}", exc_info=True)
        raise


# --- Abbreviation DB endpoints ---
@app.get("/abbrev/{short}")
async def get_abbrev(short: str, session: AsyncSession = Depends(get_session)):
    """Return a single abbreviation mapping (from DB)."""
    logger.debug(f"[get_abbrev] Looking up abbreviation: {short}")
    if not DATABASE_ENABLED:
        logger.warning(f"[get_abbrev] Database not enabled")
        return {"ok": False, "error": "DB not configured (set NLP_DATABASE_URL)"}

    row = await session.get(Abbreviation, short)
    if not row:
        logger.debug(f"[get_abbrev] Abbreviation not found: {short}")
        return {"ok": True, "found": False}

    logger.debug(f"[get_abbrev] Found: {short} -> {row.long}")
    return {
        "ok": True,
        "found": True,
        "short": row.short,
        "long": row.long,
        "source": row.source,
        "confidence": row.confidence,
        "updated_at": str(row.updated_at) if row.updated_at else None,
    }


@app.get("/abbrev/search")
async def search_abbrev(q: str, limit: int = 20, session: AsyncSession = Depends(get_session)):
    """Simple search by short/long contains (case-insensitive)."""
    if not DATABASE_ENABLED:
        return {"ok": False, "error": "DB not configured (set NLP_DATABASE_URL)"}

    q_norm = (q or "").strip()
    if not q_norm:
        return {"ok": True, "results": []}

    

    stmt = (
        select(Abbreviation)
        .where(
            or_(
                Abbreviation.short.ilike(f"%{q_norm}%"),
                Abbreviation.long.ilike(f"%{q_norm}%"),
            )
        )
        .limit(max(1, min(limit, 100)))
    )
    res = await session.execute(stmt)
    rows = res.scalars().all()

    return {
        "ok": True,
        "results": [
            {
                "short": r.short,
                "long": r.long,
                "source": r.source,
                "confidence": r.confidence,
                "updated_at": str(r.updated_at) if r.updated_at else None,
            }
            for r in rows
        ],
    }


@app.post("/abbrev/reload")
async def reload_abbrev_cache():
    """Reload the in-memory cache immediately."""
    if not DATABASE_ENABLED:
        return {"ok": False, "error": "DB not configured (set NLP_DATABASE_URL)"}

    count = await load_abbrev_cache()
    return {"ok": True, "count": count}


@app.get("/health")
def health():
    logger.debug("[health] Health check called")
    return {"ok": True}
