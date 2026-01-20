from dotenv import load_dotenv
from opensearchpy import OpenSearch
import os

class dbConnector:
  load_dotenv()
  
  _PASS = os.getenv('OPENSEARCH_INITIAL_ADMIN_PASSWORD')
  MODELS = {
		'nomic-embed-text': {
						'dimensions': 768,
						'description': 'A general-purpose text embedding model by Nomic AI, suitable for various NLP tasks including semantic search, clustering, and classification.',
						'source_index': 'v1_en_nomic-embed-text_index',
						'claims_index': 'v1_claims_nomic-embed-text_index'
		},
	}
  
  def __init__(self, model_name: str):
    try:
      host = 'localhost'
      port = 9200
      auth = ('admin', self._PASS) 
      self.model = self.MODELS[model_name]
      self.db_client = OpenSearch(
        hosts = [{'host': host, 'port': port}],
        http_compress = True,
        use_ssl = True,
        verify_certs = False,
        ssl_assert_hostname = False,
        ssl_show_warn = False,
        http_auth = auth
      )
    except KeyError as e:
      print(f"Model {model_name} not found in MODELS. valid models are: {list(self.MODELS.keys())}")
      return e

  def index_to_db(self, index_name, document):
    response = self.db_client.index(
      index = self.model[index_name],
      body = document,
      refresh=True
    )
    return response

  def create_index(self, index_name):
    index = self.model[index_name]
    body = {
      'settings': {
        'index':{
          'number_of_shards': 2,
          'number_of_replicas': 1,
          'knn': True
        }
      },
      'mappings': {
        'properties': {
          'content_for_embedding': {
            'type': 'text'
          },
          "embedding": {
            "type": "knn_vector",
            "dimension": 768,
            "method": {
              "name": "hnsw",
              "engine": "lucene",
              "space_type": "cosinesimil"
            }
          },
          'id': {
            'type': 'keyword'
          },
          'pmid': {
            'type': 'keyword'
          },
        }
      }
    }
    if not self.db_client.indices.exists(index=index):
        response = self.db_client.indices.create(index=index,body=body)
        print("Created index:", index, "with response:", response)
        return response
    else:
        return {"acknowledged": True, "message": "Index already exists"}
      
  def search_index(self, index_name, text=None ,vector=None, size=5):
    if not text and not vector:
      raise ValueError("Either text or vector must be provided for search.")
    knn_query = {
      "knn": {
        "embedding": {
          "vector": vector,
          "k": 5
        }
      }
    } 
    text_query = {
      "match": {
        "content_for_embedding": text
      }
    } 
    should_clauses = []
    if vector:
      should_clauses.append(knn_query)
    if text:
      should_clauses.append(text_query)
    body = {
      "size": 5,
      "query": {
        'bool':{
          'should':should_clauses
        }
      }
    }
    res = self.db_client.search(
      index = self.model[index_name],
      body = body
    )['hits']['hits']
    return res