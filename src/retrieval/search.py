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
      "query": {
        'bool':{
          'should':should_clauses,
          'minimum_should_match': 1,
        }
      }
    }

    logger.debug(f"[search] Executing search with {len(should_clauses)} clauses")
    result = db.search(
      index_type = 'sources_index',
      body = body
    )
    hits = result.get('hits', {}).get('hits', [])
    logger.debug(f"[search] Got {len(hits)} results from OpenSearch")

    # Log each result's ID
    for i, hit in enumerate(hits):
      doc_id = hit.get('_source', {}).get('id', hit.get('_id'))
      score = hit.get('_score')
      logger.debug(f"[search]   Result {i+1}: id='{doc_id}', score={score}")

    return hits
  except Exception as e:
    logger.exception("Search failed for text=%s", text[:100] if text else None)
    return []