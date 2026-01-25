from .router import classify_intent
from .search import search_claims, search_sources
from ..classes.ollama_connector import OllamaConnector
from .hybrid import hybrid_results
from .db_connector import dbConnector

import logging
logger = logging.getLogger(__name__)

db = dbConnector()
def run_retrieval(query: str,k_primary: int = 5, k_secondary: int = 3) -> dict:
  logger.info(f"run_retrieval: {query}")
  query_embedding = OllamaConnector.embed_text(query)
  intent = classify_intent(query)
  claims = search_claims(db, text=query, vector=query_embedding)
  sources = search_sources(db, text=query, vector=query_embedding)
  res = hybrid_results(intent, claims, sources, k_primary, k_secondary)
  return res