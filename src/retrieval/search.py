import logging
import re

__name__ = 'search'

logger = logging.getLogger(__name__)

# Keep in sync with MIN_FULLTEXT_WORDS in src/routers/conversation_helper.py —
# sources below this are kept in the index (not deleted) but excluded from
# retrieval; see scripts/backfill_full_text_word_count.py for backfilling this
# field on docs indexed before it existed.
MIN_FULLTEXT_WORDS = 20


def search_sources(db, text=None, vector=None, k_results: int = 5):
  try:
    knn_query = {
        "knn": {
          "embedding": {
            "vector": vector,
            "k": k_results * 4,
            'boost': 2
          },
        }
      }
    text_query = [{
      "match": {
        "content_for_embedding": {
          'query': text,
          'boost': 1
        },
      },
    },{
      "match": {
        "title": {
          'query': text,
          'boost': 1.5
        },
      },
    }]
    should_clauses = []
    if vector:
      should_clauses.append(knn_query)
    if text:
      should_clauses += text_query

    # Fetch more than needed so Python-side dedup still yields k_results unique sources.
    # collapse is avoided because source_id may be mapped as text (not keyword) in
    # existing indices, which causes a 400 error.
    body = {
      "size": k_results * 4,
      "query": {
        'bool':{
          'should': should_clauses,
          'minimum_should_match': 1,
          'filter': [
            {'range': {'full_text_word_count': {'gte': MIN_FULLTEXT_WORDS}}},
          ],
        }
      }
    }

    logger.info("[search] executing: text='%s' vector=%s clauses=%d",
                text[:80] if text else None, bool(vector), len(should_clauses))
    result = db.search(
      index_type = 'sources_index',
      body = body
    )
    hits = result.get('hits', {}).get('hits', [])
    total = result.get('hits', {}).get('total', {}).get('value', '?')
    logger.info("[search] returned %d raw hits (total_matching=%s)", len(hits), total)

    # Deduplicate by source_id (chunked docs) or base id (old-format docs)
    seen: set = set()
    deduped: list = []
    for hit in hits:
      src = hit.get('_source', {})
      base_id = src.get('source_id') or re.sub(r':c\d+$', '', src.get('id') or hit.get('_id') or '')
      if base_id and base_id not in seen:
        seen.add(base_id)
        deduped.append(hit)

    deduped = deduped[:k_results]
    logger.info("[search] after dedup: %d unique sources", len(deduped))
    for i, hit in enumerate(deduped):
      src = hit.get('_source', {})
      logger.info("[search]   hit %d: id='%s' source_id='%s' score=%s",
                  i + 1, src.get('id'), src.get('source_id', '(none)'), hit.get('_score'))

    return deduped
  except Exception as e:
    logger.exception("Search failed for text=%s", text[:100] if text else None)
    return []