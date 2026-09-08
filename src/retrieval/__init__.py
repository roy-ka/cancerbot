from .search import search_sources
from .db_connector import dbConnector

import logging
import os
import re
logger = logging.getLogger(__name__)

db = dbConnector()


def _rerank_sources(question: str, sources: list) -> list:
  """Reorder search_sources' already cosine-gated, capped list by cross-
  encoder relevance to the natural question — a precision pass, not a
  second relevance gate: it only reorders, it never drops a source the
  gate already let through (a multi-part question can have a source that
  only supports one part of the answer; dropping it here would repeat the
  "discard everything if not everything is supported" bug the prompt's
  citation rule was just fixed for). Fails open on any error — original
  RRF order is a reasonable result on its own, so a reranker outage must
  not break retrieval.
  """
  if os.getenv("RERANK_ENABLED", "true").strip().lower() not in ("1", "true", "yes"):
    return sources
  if len(sources) < 2:
    return sources

  # Local import: same reasoning as OllamaConnector below — keeps this
  # module free of the extra import chain unless reranking actually runs.
  from ..nlp import rerank

  documents = [s.get('_source', {}).get('content_for_embedding') or '' for s in sources]
  scores = rerank(question, documents)
  if scores is None:
    return sources

  for source, score in zip(sources, scores):
    source['_rerank_score'] = score
  return sorted(sources, key=lambda s: s.get('_rerank_score', 0.0), reverse=True)

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
  # Local import: keeps this module (and anything that merely imports the
  # src.retrieval package, e.g. scripts/backup_opensearch.py importing just
  # db_connector) free of OllamaConnector's heavier dependency chain
  # (groq, ollama) unless retrieval is actually performed.
  from ..classes.ollama_connector import OllamaConnector

  dense_text = (question or '').strip() or query
  logger.info("[retrieval] terms='%s' dense='%s' disease_areas=%s",
              query[:120], dense_text[:120], disease_areas)
  query_embedding = OllamaConnector.embed_text(dense_text)
  logger.info("[retrieval] embedding_dim=%d", len(query_embedding))
  # Called from a worker thread (asyncio.to_thread) and the result is needed
  # immediately, so this runs inline — handing it to another pool only added a
  # thread hop. search_sources already returns the relevance-gated, capped set
  # (variable count, not a fixed top-k), so there's nothing more to slice here.
  sources = search_sources(db, query, query_embedding, disease_areas=disease_areas)
  sources = _rerank_sources(dense_text, sources)

  metrics = calculate_search_metrics(query, sources)

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