from src.db.models import FallbackSearch
from uuid import uuid4


def _extract_initial_sources(generation_context: list) -> list[dict]:
    """Pull id, title, score and index name from raw OpenSearch hits."""
    out = []
    for hit in generation_context or []:
        src = hit.get("_source") or hit
        out.append({
            "id": src.get("id") or hit.get("_id"),
            "title": src.get("title"),
            "score": hit.get("_score"),
            "source_type": src.get("source_type") or src.get("abstract_source"),
            "index": hit.get("_index"),
        })
    return out


def save_fallback_search(
    db,
    conversation_id,
    message_id,
    question: str,
    initial_context: list,
    fallback_meta: dict,
    searched_web: bool = False,
) -> FallbackSearch:
    record = FallbackSearch(
        id=uuid4(),
        conversation_id=conversation_id,
        message_id=message_id,
        question=question,
        terms=fallback_meta.get("terms"),
        initial_sources=_extract_initial_sources(initial_context),
        pubmed_found=fallback_meta.get("pubmed_found"),
        crossref_found=fallback_meta.get("crossref_found"),
        wikipedia_found=fallback_meta.get("wikipedia_found"),
        indexed=fallback_meta.get("indexed"),
        searched_web=searched_web,
    )
    db.add(record)
    db.commit()
    return record


def get_fallback_searches(db, limit: int = 50) -> list[FallbackSearch]:
    return (
        db.query(FallbackSearch)
        .order_by(FallbackSearch.created_at.desc())
        .limit(limit)
        .all()
    )
