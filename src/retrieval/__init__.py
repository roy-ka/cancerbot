from .search import search_sources
from ..classes.ollama_connector import OllamaConnector
from .db_connector import dbConnector
from concurrent.futures import ThreadPoolExecutor

import logging
logger = logging.getLogger(__name__)

db = dbConnector()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="opensearch")

def run_retrieval(query: str, k_primary: int = 5, k_secondary: int = 3) -> dict:
  logger.info(f"[retrieval] Starting retrieval for query='{query}'")
  query_embedding = OllamaConnector.embed_text(query)
  logger.info(f"[retrieval] Generated embedding with dim={len(query_embedding)}")

  logger.debug(f"[retrieval] Submitting search to thread pool...")
  fut_sources = _executor.submit(search_sources, db, query, query_embedding)
  sources = fut_sources.result()
  logger.info(f"[retrieval] Search returned {len(sources)} results")

  sources = sources[:k_primary]
  logger.debug(f"[retrieval] Trimmed to top {len(sources)} results for generation context")

  # Extract source IDs with detailed logging
  source_ids = []
  for i, source in enumerate(sources):
    source_obj = source.get('_source', {})
    doc_id = source_obj.get('id')
    if doc_id:
      source_ids.append(doc_id)
      logger.debug(f"[retrieval]   Source {i+1}: id='{doc_id}'")
    else:
      logger.warning(f"[retrieval]   Source {i+1}: Missing 'id' field! Full source: {source_obj.keys()}")

  res = {
    'generation_context': sources,
    'sources_ids': source_ids,
  }
  logger.info(f"[retrieval] Completed: {len(res['generation_context'])} context items, {len(source_ids)} source IDs")
  return res