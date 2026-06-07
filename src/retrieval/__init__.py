from .search import search_sources
from ..classes.ollama_connector import OllamaConnector
from .db_connector import dbConnector
from concurrent.futures import ThreadPoolExecutor

import logging
logger = logging.getLogger(__name__)

db = dbConnector()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="opensearch")

def calculate_search_metrics(query: str, results: list) -> dict:
  """Calculate search metrics from results (scores are in 0-1 range, convert to 0-100)."""
  scores = [r.get('_score', 0) for r in results if isinstance(r, dict)]

  result_count = len(results)
  top_score = int(scores[0] * 100) if scores else None
  avg_score = int((sum(scores) / len(scores)) * 100) if scores else None
  min_score = int(scores[-1] * 100) if scores else None

  return {
    'search_query': query[:500],
    'result_count': result_count,
    'top_score': top_score,
    'avg_score': avg_score,
    'min_score': min_score,
  }

def run_retrieval(query: str, k_primary: int = 5, k_secondary: int = 3) -> dict:
  logger.info(f"[retrieval] Starting retrieval for query='{query}'")
  query_embedding = OllamaConnector.embed_text(query)
  logger.info(f"[retrieval] Generated embedding with dim={len(query_embedding)}")

  logger.debug(f"[retrieval] Submitting search to thread pool...")
  fut_sources = _executor.submit(search_sources, db, query, query_embedding)
  sources = fut_sources.result()
  logger.info(f"[retrieval] Search returned {len(sources)} results")

  # Calculate metrics for all results before trimming
  metrics = calculate_search_metrics(query, sources)
  all_scores = [s.get('_score', 0) for s in sources if isinstance(s, dict)]
  if all_scores:
    logger.info(f"[retrieval] Score distribution: top={all_scores[0]:.2f}, avg={sum(all_scores)/len(all_scores):.2f}, min={all_scores[-1]:.2f}")

  sources = sources[:k_primary]
  logger.debug(f"[retrieval] Trimmed to top {len(sources)} results for generation context")

  # Extract source IDs with detailed logging
  source_ids = []
  for i, source in enumerate(sources):
    source_obj = source.get('_source', {})
    doc_id = source_obj.get('id')
    score = source.get('_score', 0)
    if doc_id:
      source_ids.append(doc_id)
      logger.debug(f"[retrieval]   Source {i+1}: id='{doc_id}' score={score:.2f}")
    else:
      logger.warning(f"[retrieval]   Source {i+1}: Missing 'id' field! Full source: {source_obj.keys()}")

  res = {
    'generation_context': sources,
    'sources_ids': source_ids,
    'search_metrics': metrics,  # Include metrics for analytics recording
  }
  logger.info(f"[retrieval] Completed: {len(res['generation_context'])} context items, {len(source_ids)} source IDs")

  return res