from dotenv import load_dotenv
from opensearchpy import OpenSearch
import os
import ssl
import logging
from src.utils.utils import is_prod

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
      'claims_index': 'v1.5_claims_nomic-embed-text_index',
    },
  }

  db_client = None
  _initialized = False
  _model = None

  @classmethod
  def _initialize(cls):
    if cls._initialized:
      return
    cls._initialized = True

    if not model_name or not cls._PASS:
      cls.logger.warning("OpenSearch not configured (missing EMBED_MODEL_NAME or OPENSEARCH_INITIAL_ADMIN_PASSWORD)")
      return

    try:
      if model_name not in cls.MODELS:
        raise KeyError(f"EMBED_MODEL_NAME='{model_name}' not found in MODELS. Valid models: {list(cls.MODELS.keys())}")

      cls._model = cls.MODELS[model_name]
      from urllib.parse import urlparse
      _parsed = urlparse(os.getenv('OPENSEARCH_URL', 'https://localhost:9200'))
      host = _parsed.hostname or 'localhost'
      port = _parsed.port or 9200
      auth = ('admin', cls._PASS)
      verify_certs = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() in ("1", "true", "yes")
      if not verify_certs and is_prod():
        cls.logger.warning("OPENSEARCH_VERIFY_CERTS is disabled in production — TLS certificate not verified")

      ssl_kwargs = {}
      if is_prod() and not verify_certs:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        ssl_kwargs['ssl_context'] = ssl_context

      cls.db_client = OpenSearch(
        hosts=[{'host': host, 'port': port}],
        http_compress=True,
        use_ssl=True,
        verify_certs=verify_certs,
        ssl_assert_hostname=verify_certs,
        ssl_show_warn=not verify_certs,
        http_auth=auth,
        **ssl_kwargs
      )
    except KeyError as e:
      raise KeyError(str(e))
    except Exception as e:
      cls.logger.warning(f"Failed to initialize OpenSearch client: {e}")
      cls.db_client = None
      cls._model = None

  @classmethod
  def index_to_db(cls, index_name, document):
    cls._initialize()
    if not cls.db_client:
      raise RuntimeError("OpenSearch client not available")

    index_name_mapped = cls._model[index_name]
    doc_id = document.get('id', 'unknown')
    cls.logger.debug(f"[OpenSearch] Indexing document '{doc_id}' to index '{index_name_mapped}'")

    try:
      response = cls.db_client.index(
        index=index_name_mapped,
        body=document,
        refresh=True
      )
      cls.logger.debug(f"[OpenSearch] Successfully indexed '{doc_id}': {response.get('_id')}")
      return response
    except Exception as e:
      cls.logger.error(f"[OpenSearch] Failed to index '{doc_id}': {e}")
      raise

  @classmethod
  def ensure_all_indexes(cls):
    """Ensure all required indexes exist. Create them if they don't."""
    cls._initialize()
    if not cls.db_client or not cls._model:
      cls.logger.warning("OpenSearch not available, skipping index initialization")
      return False

    indexes_to_create = ['sources_index', 'claims_index']
    all_created = True

    for index_key in indexes_to_create:
      if index_key not in cls._model:
        cls.logger.warning(f"Index key '{index_key}' not found in model configuration")
        continue

      try:
        cls.create_index(index_key)
      except Exception as e:
        cls.logger.error(f"Failed to ensure index {index_key}: {e}")
        all_created = False

    return all_created

  @classmethod
  def create_index(cls, index_name):
    cls._initialize()
    if not cls.db_client:
      raise RuntimeError("OpenSearch client not available")

    index = cls._model[index_name]
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
    cls._initialize()
    if not cls.db_client:
      raise RuntimeError("OpenSearch client not available")

    index_name = cls._model[index_type]
    query = body.get('query', {})
    cls.logger.debug(f"[OpenSearch] Searching index '{index_name}' with query: {query}")

    try:
      res = cls.db_client.search(
        index=index_name,
        body=body
      )
      hit_count = len(res.get('hits', {}).get('hits', []))
      total_hits = res.get('hits', {}).get('total', {}).get('value', 0)
      cls.logger.debug(f"[OpenSearch] Search returned {hit_count} results (total: {total_hits})")

      # Log document IDs found
      if hit_count > 0:
        doc_ids = [hit.get('_source', {}).get('id', hit.get('_id')) for hit in res['hits']['hits']]
        cls.logger.debug(f"[OpenSearch] Found document IDs: {doc_ids}")

      return res
    except Exception as e:
      cls.logger.error(f"[OpenSearch] Search failed: {e}")
      raise

  @classmethod
  def existing_source_ids(cls, ids: list) -> set:
    """Return the subset of `ids` that already exist in the sources index."""
    if not ids:
      return set()
    cls._initialize()
    if not cls.db_client:
      return set()
    res = cls.db_client.search(
      index=cls._model['sources_index'],
      body={
        'size': len(ids),
        '_source': ['id'],
        'query': {'terms': {'id': ids}},
      }
    )
    return {hit['_source']['id'] for hit in res['hits']['hits'] if hit.get('_source', {}).get('id')}

  @classmethod
  def get_sources_by_id(cls, ids):
    if not ids:
      return {'hits': {'hits': []}}
    cls._initialize()
    if not cls.db_client:
      return {'hits': {'hits': []}}

    return cls.db_client.search(
      index=cls._model['sources_index'],
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

  @classmethod
  def get_claims_and_sources_by_id(cls, ids):
    """Get claims and sources by their IDs from both indices."""
    if not ids:
      return {'hits': {'hits': []}}
    cls._initialize()
    if not cls.db_client:
      return {'hits': {'hits': []}}

    return cls.db_client.search(
      index=f"{cls._model['sources_index']}*",
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
