import re
from typing import List

# Keywords/phrases that suggest the user is asking for an explanation / background.
concept_words = [
    "what is",
    "definition",
    "effect",
    "mechanism",
    "pathway",
    "origin",
    "role of",
    "how does",
    "biology",
    "metabolism",
    "glycolysis",
    "warburg",
]

# Keywords/phrases that suggest the user is asking what to do / take / change.
intervention_words = [
    "should i",
    "use",
    "take",
    "diet",
    "supplement",
    "therapy",
    "treatment",
    "protocol",
    "improve",
    "reduce",
    "lower",
    "fasting",
    "ketogenic",
    "metformin",
    "aspirin",
    "vitamin",
]

# These are *ordering directives* used by hybrid_results.
concept: List[str] = ["sources", "claims"]
intervention: List[str] = ["claims", "sources"]


def _matches_any(query_lower: str, terms: List[str]) -> bool:
    """Return True if any term matches.

    - For multi-word phrases: substring match.
    - For single words: word-boundary match to reduce false positives.
    """
    for term in terms:
        t = term.lower().strip()
        if not t:
            continue
        if " " in t:
            if t in query_lower:
                return True
        else:
            if re.search(rf"\b{re.escape(t)}\b", query_lower):
                return True
    return False


def classify_intent(query: str) -> List[str]:
    q = (query or "").lower()

    # Prefer intervention when both match (e.g., "what is metformin" is likely actionable).
    if _matches_any(q, intervention_words):
        return intervention
    if _matches_any(q, concept_words):
        return concept

    # Default: concept/explanatory.
    return concept
