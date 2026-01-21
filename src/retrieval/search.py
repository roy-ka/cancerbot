import logging

__name__ = 'search'

logger = logging.getLogger(__name__)

def search_claims(db,text=None ,vector=None):
  knn_query = {
    "knn": {
      "embedding": {
        "vector": vector,
        "k": 5,
        'boost': 2
      },
    }
  } 
  text_query = [{
    'match': {
      'protocol_claim_en': {
        'query': text,
        'boost': 1.5
      },
    },
  },{
    'match': {
      'risk_flags': {
        'query': text,
        'boost': 0.5
      },
    },
  },{
    'match': {
      'tags': {
        'query': text,
        'boost': 1
      },
    },
  },{
    'match': {
      'key_evidence.citation': {
        'query': text,
        'boost': 1
      },
    },
  }]
  should_clauses = []
  if vector:
    should_clauses.append(knn_query)
  if text:
    should_clauses += text_query
  body = {
    "size": 3,
    "query": {
      'bool':{
        'should':should_clauses,
        'minimum_should_match': 1,
      }
    }
  }
  logger.info(f"Search body: {body}")
  return db.search(
    index_type = 'claims_index',
    body = body
  )
  
  

def search_sources(db, text=None ,vector=None):
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
  if text:
    should_clauses += text_query
  body = {
    "size": 5,
    "query": {
      'bool':{
        'should':should_clauses,
        'minimum_should_match': 1,
      }
    }
  }
  logger.info(f"Search body: {body}")
  return db.search(
    index_type = 'sources_index',
    body = body
  )