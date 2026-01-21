from .router import classify_intent
from .search import search_claims, search_sources
from ..classes.ollama_connector import OllamaConnector
from .hybrid import hybrid_results
from .db_connector import db

def run_retrieval(query: str):
  query_embedding = OllamaConnector.embed_text(query)
  intents = classify_intent(query)
  claims = search_claims(db, text=query, vector=query_embedding)
  sources = search_sources(db, text=query, vector=query_embedding)
  return hybrid_results(intents, claims, sources)