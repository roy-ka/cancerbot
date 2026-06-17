import asyncio
import logging

from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

_nlp = None
_spell_checker = None
_abbrev_cache: dict[str, str] = {}
_abbrev_cache_lock = asyncio.Lock()

_STOP_ENTS = frozenset({"cancer", "tumor"})


def load_models() -> None:
    """Load spacy model and spell checker. Call once at startup."""
    global _nlp, _spell_checker
    import spacy
    import scispacy  # noqa: F401 — registers scispaCy pipeline components
    import scispacy.abbreviation  # noqa: F401 — registers abbreviation_detector factory
    from spellchecker import SpellChecker

    logger.info("[nlp] Loading en_core_sci_sm...")
    _nlp = spacy.load("en_core_sci_sm")
    if "abbreviation_detector" not in _nlp.pipe_names:
        _nlp.add_pipe("abbreviation_detector", last=True)
    logger.info("[nlp] Pipeline ready: %s", _nlp.pipe_names)

    _spell_checker = SpellChecker(distance=1)
    logger.info("[nlp] SpellChecker ready")


def _preserve_case(original: str, corrected: str) -> str:
    if original.isupper():
        return corrected.upper()
    if original[:1].isupper():
        return corrected.capitalize()
    return corrected


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        term = " ".join((x or "").split()).strip()
        if term and term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    return out


def _apply_spell_corrections(doc, cache_snapshot: dict[str, str]) -> str:
    """Apply spell corrections to an existing spaCy doc, protecting known terms."""
    protected: set[str] = set()
    for ent in doc.ents:
        for tok in ent:
            if tok.text.strip():
                protected.add(tok.text.strip().lower())
    for abbr in doc._.abbreviations:
        if str(abbr).strip():
            protected.add(str(abbr).strip().lower())
        if str(abbr._.long_form).strip():
            protected.add(str(abbr._.long_form).strip().lower())
    protected.update(cache_snapshot.keys())

    parts: list[str] = []
    for tok in doc:
        raw = tok.text
        lower = raw.lower()
        fixed = raw
        if (
            _spell_checker is not None
            and tok.is_alpha
            and len(raw) >= 4
            and not raw.isupper()
            and lower not in protected
            and "'" not in raw
            and _spell_checker.unknown([lower])
        ):
            suggestion = _spell_checker.correction(lower)
            if (
                suggestion
                and suggestion != lower
                and suggestion[0] == lower[0]
                and abs(len(suggestion) - len(lower)) <= 2
            ):
                fixed = _preserve_case(raw, suggestion)
        parts.append(f"{fixed}{tok.whitespace_}")
    return "".join(parts)


async def correct_spelling(text: str) -> str:
    """Return spell-corrected text, protecting known scientific entities and abbreviations."""
    text = " ".join((text or "").split()).strip()
    if not text or _nlp is None or _spell_checker is None:
        return text
    doc = await run_in_threadpool(_nlp, text)
    async with _abbrev_cache_lock:
        cache_snapshot = dict(_abbrev_cache)
    return _apply_spell_corrections(doc, cache_snapshot)


async def extract_terms(text: str) -> list[str]:
    """Extract scientific entities via spaCy. Returns a deduplicated term list."""
    if not text:
        return []
    if _nlp is None:
        logger.warning("[nlp] extract_terms called but NLP model is not loaded — load_models() was not called at startup")
        return []

    text_norm = " ".join(text.split()).strip()
    doc = await run_in_threadpool(_nlp, text_norm)

    entities = [
        e.text.strip()
        for e in doc.ents
        if e.text.strip() and e.text.strip().lower() not in _STOP_ENTS
    ]
    # Normalise keys to lowercase so lookups via e.lower() always match
    abbr_found = {str(a).strip().lower(): str(a._.long_form).strip() for a in doc._.abbreviations}

    if abbr_found:
        async with _abbrev_cache_lock:
            for short, long_form in abbr_found.items():
                if short:
                    _abbrev_cache[short] = long_form

    # Single snapshot after writing new abbreviations — reused for all entity lookups
    async with _abbrev_cache_lock:
        cache_snapshot = dict(_abbrev_cache)

    expanded: list[str] = []
    for e in entities:
        key = e.lower()
        if key in abbr_found:
            expanded.append(abbr_found[key])
        else:
            expanded.append(cache_snapshot.get(key) or e)

    return _dedupe([*expanded, *entities])
