import logging

__name__ = 'search'

logger = logging.getLogger(__name__)


def search_sources(db, text=None ,vector=None):
  try:
    logger.debug(f"[search] Starting search: text='{text[:50] if text else None}...', vector_dim={len(vector) if vector else None}")

    knn_query = {
        "knn": {
          "embedding": {
            "vector": vector,
            "k": 5,
            'boost': 2
          },
        }
      }
    text_query =  [{
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
      logger.debug("[search] Added KNN query clause")
    if text:
      should_clauses += text_query
      logger.debug("[search] Added text query clauses")

    body = {
      "size": 5,
      "collapse": {
        "field": "source_id",
      },
      "query": {
        'bool':{
          'should':should_clauses,
          'minimum_should_match': 1,
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
    logger.info("[search] returned %d hits (total_matching=%s)", len(hits), total)

    for i, hit in enumerate(hits):
      doc_id = hit.get('_source', {}).get('id', hit.get('_id'))
      source_id = hit.get('_source', {}).get('source_id', '(none)')
      score = hit.get('_score')
      logger.info("[search]   hit %d: id='%s' source_id='%s' score=%s", i + 1, doc_id, source_id, score)

    return hits
  except Exception as e:
    logger.exception("Search failed for text=%s", text[:100] if text else None)
    return []