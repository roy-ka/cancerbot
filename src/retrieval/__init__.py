from .search import search_sources
from ..classes.ollama_connector import OllamaConnector
from .db_connector import dbConnector
from concurrent.futures import ThreadPoolExecutor

import logging
logger = logging.getLogger(__name__)

db = dbConnector()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="opensearch")

def run_retrieval(query: str, k_primary: int = 5, k_secondary: int = 3) -> dict:
  logger.info(f"[retrieval] query='{query}'")
  query_embedding = OllamaConnector.embed_text(query)
  logger.info(f"[retrieval] embedding done, vector dim={len(query_embedding)}")

  fut_sources = _executor.submit(search_sources, db, query, query_embedding)
  sources = fut_sources.result()
  logger.info(f"[retrieval] search done: sources={len(sources)}")

  sources = sources[:k_primary]
  res = {
    'generation_context': sources,
    'sources_ids': [s['_source'].get('id') for s in sources if s.get('_source', {}).get('id')],
  }
  logger.info(f"[retrieval] done: generation_context={len(res['generation_context'])} items, sources_ids={res['sources_ids']}")
  return res