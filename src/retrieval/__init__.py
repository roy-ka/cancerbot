from .search import search_sources
from ..classes.ollama_connector import OllamaConnector
from .db_connector import dbConnector

import logging
import re
logger = logging.getLogger(__name__)

db = dbConnector()

def calculate_search_metrics(query: str, results: list) -> dict:
  """Calculate search metrics from results.

  Scores are stored **raw**, exactly as search_sources returns them (currently
  fused RRF scores, roughly 0.01–0.03). They are not relevance percentages.
  This function used to multiply by 100 and truncate to int on the assumption
  that scores were 0–1; the hybrid query's scores never were (~5–20 observed),
  so every row recorded a meaningless ~500–2000. Rows written before the
  columns became floats are unusable for tuning — ignore them when analysing
  search_analytics.
  """
  scores = [r.get('_score') or 0.0 for r in results if isinstance(r, dict)]

  return {
    'search_query': query[:500],
    'result_count': len(results),
    'top_score': max(scores) if scores else None,
    'avg_score': sum(scores) / len(scores) if scores else None,
    'min_score': min(scores) if scores else None,
  }

def run_retrieval(
  query: str,
  k_primary: int = 5,
  disease_areas: list | None = None,
  question: str | None = None,
) -> dict:
  """Retrieve sources for a message.

  `query` is the lexical query — NLP-extracted representative terms, chosen to
  stop noise words and synonym expansion from skewing BM25. `question` is the
  user's natural-language message, used for the dense half: the terms were
  picked to fix keyword-matching behaviour, and a sentence is closer to what
  the embedding model was trained on. Falls back to `query` when absent.
  """
  dense_text = (question or '').strip() or query
  logger.info("[retrieval] terms='%s' dense='%s' disease_areas=%s",
              query[:120], dense_text[:120], disease_areas)
  query_embedding = OllamaConnector.embed_text(dense_text)
  logger.info("[retrieval] embedding_dim=%d", len(query_embedding))
  # Called from a worker thread (asyncio.to_thread) and the result is needed
  # immediately, so this runs inline — handing it to another pool only added a
  # thread hop.
  sources = search_sources(db, query, query_embedding, k_primary, disease_areas)

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