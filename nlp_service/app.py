import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from starlette.concurrency import run_in_threadpool
from synonyms import get_synonyms, _FORWARD, _REVERSE

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _init_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    sentry_sdk.init(
        dsn=dsn,
        integrations=[
            FastApiIntegration(),
            StarletteIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        environment="production",
        traces_sample_rate=0.1,
        send_default_pii=False,
        enable_logs=True,
    )
    logger.info("[NLP] Sentry initialized")


if os.getenv("ENV", "").lower() in ("prod", "production"):
    _init_sentry()


STOP_ENTS = frozenset({
    "cancer", "tumor",
    "how", "why", "when", "where", "who", "which", "what",
    "does", "do", "did", "is", "are", "was", "were", "be", "been",
    "can", "could", "will", "would", "should", "may", "might",
    "not", "no", "yes", "also", "just", "very", "more", "most",
    "about", "like", "such", "than", "then", "there", "here",
    "tell", "give", "show", "explain", "describe", "list", "find",
    "know", "need", "want", "help", "make", "look", "take", "get",
    "use", "see", "say", "let", "put", "ask",
})


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("[lifespan] Startup complete")
    yield
    logger.info("[lifespan] Shutdown")


app = FastAPI(title="Cancerbot NLP Service", lifespan=lifespan)

logger.info("[startup] Loading spacy model 'en_core_sci_sm'...")
import spacy
import scispacy  # noqa: F401
import scispacy.abbreviation  # noqa: F401
from spellchecker import SpellChecker

nlp = spacy.load("en_core_sci_sm")
if "abbreviation_detector" not in nlp.pipe_names:
    nlp.add_pipe("abbreviation_detector", last=True)
logger.info("[startup] Pipeline: %s", nlp.pipe_names)

spell_checker = SpellChecker(distance=1)
logger.info("[startup] SpellChecker ready")


class ExtractReq(BaseModel):
    text: str


class SpellingReq(BaseModel):
    text: str


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        term = " ".join((x or "").split()).strip()
        if term and term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    return out


def _preserve_case(original: str, corrected: str) -> str:
    if original.isupper():
        return corrected.upper()
    if original[:1].isupper():
        return corrected.capitalize()
    return corrected


@app.post("/extract")
async def extract(req: ExtractReq):
    t0 = time.time()
    logger.info("[extract] input: %r", (req.text or "")[:200])
    doc = await run_in_threadpool(nlp, req.text or "")

    entities = [
        e.text.strip()
        for e in doc.ents
        if e.text.strip() and e.text.strip().lower() not in STOP_ENTS
    ]

    abbr_found: dict[str, str] = {
        str(a).strip().lower(): str(a._.long_form).strip()
        for a in doc._.abbreviations
        if str(a).strip() and str(a._.long_form).strip()
    }

    # Also scan every token against the synonym map so known abbreviations and
    # oncology terms (e.g. "GBM", "NSCLC") are caught even when scispaCy NER misses them.
    ent_keys = {e.lower() for e in entities}
    for token in doc:
        word = token.text.strip()
        if not word or word.lower() in STOP_ENTS or word.lower() in ent_keys:
            continue
        if word.lower() in _FORWARD or word.lower() in _REVERSE:
            entities.append(word)
            ent_keys.add(word.lower())

    expanded = [abbr_found.get(e.lower()) or e for e in entities]

    synonyms: list[str] = []
    for e in entities:
        synonyms.extend(get_synonyms(e))

    result = {
        "entities": _dedupe(entities),
        "expanded_entities": _dedupe(expanded),
        "synonyms": _dedupe(synonyms),
        "abbreviations_found": abbr_found,
    }
    logger.info(
        "[extract] %.3fs — entities=%s abbr=%s expanded=%s synonyms=%s",
        time.time() - t0,
        result["entities"],
        abbr_found,
        result["expanded_entities"],
        result["synonyms"],
    )
    return result


@app.post("/spelling/correct")
async def spelling_correct(req: SpellingReq):
    t0 = time.time()
    text = " ".join((req.text or "").split()).strip()
    if not text:
        return {"text": req.text, "corrected": req.text, "changes": []}

    doc = await run_in_threadpool(nlp, text)

    protected: set[str] = set()
    for ent in doc.ents:
        for tok in ent:
            if tok.text.strip():
                protected.add(tok.text.strip().lower())
    for abbr in doc._.abbreviations:
        protected.add(str(abbr).strip().lower())
        protected.add(str(abbr._.long_form).strip().lower())

    parts: list[str] = []
    changes: list[dict] = []
    for tok in doc:
        raw = tok.text
        fixed = raw
        lower = raw.lower()
        if (
            tok.is_alpha
            and len(raw) >= 4
            and not raw.isupper()
            and lower not in protected
            and "'" not in raw
            and spell_checker.unknown([lower])
        ):
            suggestion = spell_checker.correction(lower)
            if (
                suggestion
                and suggestion != lower
                and suggestion[0] == lower[0]
                and abs(len(suggestion) - len(lower)) <= 2
            ):
                fixed = _preserve_case(raw, suggestion)
                changes.append({"from": raw, "to": fixed})
        parts.append(f"{fixed}{tok.whitespace_}")

    corrected = "".join(parts)
    logger.info("[spelling] %.3fs — %d changes", time.time() - t0, len(changes))
    return {"text": req.text, "corrected": corrected, "changes": changes}


@app.get("/health")
def health():
    return {"ok": True}
