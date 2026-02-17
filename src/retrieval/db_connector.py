from dotenv import load_dotenv
from opensearchpy import OpenSearch
import os
import logging

load_dotenv()

model_name = os.getenv('EMBED_MODEL_NAME')


class dbConnector:
  __name__ = 'dbConnector'

  logger = logging.getLogger(__name__)
  load_dotenv()

  _PASS = os.getenv('OPENSEARCH_INITIAL_ADMIN_PASSWORD')
  MODELS = {
    'nomic-embed-text': {
      'dimensions': 768,
      'description': 'A general-purpose text embedding model by Nomic AI, suitable for various NLP tasks including semantic search, clustering, and classification.',
      'sources_index': 'v1.5_en_nomic-embed-text_index',
      'claims_index': 'v1.5_claims_nomic-embed-text_index'
    },
  }

  try:
    host = 'localhost'
    port = 9200
    auth = ('admin', _PASS)
    model = MODELS[model_name]
    db_client = OpenSearch(
      hosts=[{'host': host, 'port': port}],
      http_compress=True,
      use_ssl=True,
      verify_certs=False,
      ssl_assert_hostname=False,
      ssl_show_warn=False,
      http_auth=auth
    )
  except KeyError:
    print(f"Model {model_name} not found in MODELS. valid models are: {list(MODELS.keys())}")

  @classmethod
  def index_to_db(cls, index_name, document):
    response = cls.db_client.index(
      index=cls.model[index_name],
      body=document,
      refresh=True
    )
    return response

  @classmethod
  def create_index(cls, index_name):
    index = cls.model[index_name]
    body = {
      'settings': {
        'index': {
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
          'embedding': {
            'type': 'knn_vector',
            'dimension': 768,
            'method': {
              'name': 'hnsw',
              'engine': 'lucene',
              'space_type': 'cosinesimil'
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

    if not cls.db_client.indices.exists(index=index):
      response = cls.db_client.indices.create(index=index, body=body)
      cls.logger.info("Created index: %s", index)
      return response
    else:
      return {'acknowledged': True, 'message': 'Index already exists'}

  @classmethod
  def search(cls, index_type, body):
    res = cls.db_client.search(
      index=cls.model[index_type],
      body=body
    )
    return res

  @classmethod
  def get_claims_and_sources_by_id(cls, ids):
    if not ids:
      return {'hits': {'hits': []}}

    return cls.db_client.search(
      index=[cls.model['claims_index'], cls.model['sources_index']],
      body={
        'size': 200,
        '_source': True,
        'query': {
          'terms': {
            'id': ids
          }
        }
      }
    )