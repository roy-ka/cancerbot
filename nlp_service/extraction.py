"""Model loading and pure extraction/spelling logic for the NLP service.

Split out of app.py so this can be imported (and tested) without also
loading the CrossEncoder reranker — app.py eagerly loads that (torch +
sentence-transformers) at import time, which is a heavy, unrelated
dependency for anything that only needs entity extraction or spell
correction.
"""
import logging

logger = logging.getLogger(__name__)

logger.info("[startup] Loading spacy model 'en_core_sci_sm'...")
import spacy
import scispacy  # noqa: F401
import scispacy.abbreviation  # noqa: F401
from spellchecker import SpellChecker
from synonyms import get_synonyms, get_category, _FORWARD, _REVERSE

nlp = spacy.load("en_core_sci_sm")
if "abbreviation_detector" not in nlp.pipe_names:
    nlp.add_pipe("abbreviation_detector", last=True)
logger.info("[startup] Pipeline: %s", nlp.pipe_names)

spell_checker = SpellChecker(distance=1)
logger.info("[startup] SpellChecker ready")


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

# POS tags that can plausibly anchor a real (medical) entity. An entity span
# with none of these — every token a pronoun, auxiliary, determiner, bare
# verb, etc. — is a scispaCy false positive, not a term worth searching on.
# en_core_sci_sm is trained on clean scientific abstracts, not first-person
# conversational text, and over-fires on short/unusual tokens outside that
# domain: "I" (PRON) and "meant" (VERB) both came back tagged as entities on
# real user messages like "I meant how many I can have in total?" — neither
# is in STOP_ENTS (a hand-maintained list that can only ever catch words
# already seen), so this generalizes the fix instead of playing whack-a-mole
# with every future false positive of the same shape.
_CONTENT_POS = frozenset({"NOUN", "PROPN", "ADJ", "NUM"})


def _has_content_word(span) -> bool:
    return any(tok.pos_ in _CONTENT_POS for tok in span)


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


def extract_entities(text: str) -> dict:
    doc = nlp(text or "")

    entities = [
        e.text.strip()
        for e in doc.ents
        if e.text.strip() and e.text.strip().lower() not in STOP_ENTS and _has_content_word(e)
    ]

    abbr_found: dict[str, str] = {
        str(a).strip().lower(): str(a._.long_form).strip()
        for a in doc._.abbreviations
        if str(a).strip() and str(a._.long_form).strip()
    }

    # Also scan every token against the synonym map so known abbreviations and
    # oncology terms (e.g. "GBM", "NSCLC") are caught even when scispaCy NER misses them.
    # No POS filter here — a token only matches if it's a key in the curated
    # oncology synonym dict, which by construction never contains pronouns or
    # function words, so the false-positive problem above doesn't apply.
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
    entity_groups: list[dict] = []
    for e in _dedupe(entities):
        e_synonyms = _dedupe(get_synonyms(e))[:3]
        synonyms.extend(e_synonyms)
        entity_groups.append({"term": e, "synonyms": e_synonyms, "category": get_category(e)})

    return {
        "entities": _dedupe(entities),
        "expanded_entities": _dedupe(expanded),
        "synonyms": _dedupe(synonyms),
        "entity_groups": entity_groups,
        "abbreviations_found": abbr_found,
    }


def correct_spelling_text(text: str) -> dict:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return {"text": text, "corrected": text, "changes": []}

    doc = nlp(normalized)

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
    return {"text": text, "corrected": corrected, "changes": changes}
