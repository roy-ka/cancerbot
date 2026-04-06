from .router import classify_intent
from .search import search_claims, search_sources
from ..classes.ollama_connector import OllamaConnector
from .hybrid import hybrid_results
from .db_connector import dbConnector
from concurrent.futures import ThreadPoolExecutor, as_completed

import logging
logger = logging.getLogger(__name__)

db = dbConnector()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="opensearch")

def run_retrieval(query: str, k_primary: int = 5, k_secondary: int = 3) -> dict:
  logger.info(f"[retrieval] query='{query}'")
  query_embedding = OllamaConnector.embed_text(query)
  logger.info(f"[retrieval] embedding done, vector dim={len(query_embedding)}")

  intent = classify_intent(query)
  logger.info(f"[retrieval] intent={intent}")

  fut_claims = _executor.submit(search_claims, db, query, query_embedding)
  fut_sources = _executor.submit(search_sources, db, query, query_embedding)
  claims = fut_claims.result()
  sources = fut_sources.result()
  logger.info(f"[retrieval] search done: claims={len(claims)} sources={len(sources)}")

  res = hybrid_results(intent, claims, sources, k_primary, k_secondary)
  logger.info(f"[retrieval] hybrid done: generation_context={len(res.get('generation_context', []))} items, claims_ids={res.get('claims_ids')}, sources_ids={res.get('sources_ids')}")
  return res