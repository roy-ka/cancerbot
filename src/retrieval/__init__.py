from .search import search_sources
from ..classes.ollama_connector import OllamaConnector
from .db_connector import dbConnector
from concurrent.futures import ThreadPoolExecutor

import logging
import re
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
  logger.info("[retrieval] query='%s'", query[:120])
  query_embedding = OllamaConnector.embed_text(query)
  logger.info("[retrieval] embedding_dim=%d", len(query_embedding))
  fut_sources = _executor.submit(search_sources, db, query, query_embedding)
  sources = fut_sources.result()

  metrics = calculate_search_metrics(query, sources)
  sources = sources[:k_primary]

  source_ids = []
  for i, source in enumerate(sources):
    source_obj = source.get('_source', {})
    doc_id = re.sub(r':c\d+$', '', source_obj.get('id') or '')
    if doc_id:
      source_ids.append(doc_id)
    else:
      logger.warning(f"[retrieval] source {i+1} missing 'id' field")

  logger.info(f"[retrieval] sources={len(source_ids)} top_score={metrics.get('top_score')}")

  return {
    'generation_context': sources,
    'sources_ids': source_ids,
    'search_metrics': metrics,
  }