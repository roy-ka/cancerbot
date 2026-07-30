"""Text embeddings via the Hugging Face Inference API.

Replaces the Ollama-backed embedding path. Note that the model here produces
384-dimensional vectors, whereas the OpenSearch `embedding` field is mapped as
a 768-dimensional knn_vector (see src/retrieval/db_connector.py) — see the
dimension note on EMBED_DIMENSIONS below before using this in the live index.
"""

import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# all-MiniLM-L6-v2 emits 384 floats per text. The sources index is created with
# `dimension: 768` (dbConnector.create_index) because nomic-embed-text emits
# 768, and OpenSearch rejects a vector whose length doesn't match the mapping.
# Switching models therefore needs a new index and a full re-embed, not just a
# different connector.
EMBED_DIMENSIONS = 384


class _InferenceClientProxy:
  """Lazy proxy for the Hugging Face InferenceClient.

  Built on first use rather than at import so that merely importing this module
  (which happens throughout the app and in tests) doesn't require the API key
  to be present.
  """
  _client = None

  def _ensure_client(self):
    if _InferenceClientProxy._client is None:
      from huggingface_hub import InferenceClient

      api_key = os.getenv("HUGGINGFACE_API_KEY")
      if not api_key:
        raise ValueError("HUGGINGFACE_API_KEY is not set.")
      _InferenceClientProxy._client = InferenceClient(api_key=api_key)
    return _InferenceClientProxy._client

  def __getattr__(self, name):
    return getattr(self._ensure_client(), name)


class EmbeddingConnector:
  __name__ = 'Embedding_connector'

  embed_model = os.getenv("HUGGINGFACE_EMBED_MODEL", EMBED_MODEL)
  client = _InferenceClientProxy()

  @classmethod
  def _to_float_list(cls, raw) -> list[float]:
    """Coerce a feature_extraction result into a flat list of floats.

    The API returns a numpy array for sentence-transformers models. Some models
    return per-token vectors (a 2-D result) instead of a single sentence
    vector; those are mean-pooled so the caller always gets one vector.
    """
    if hasattr(raw, "tolist"):
      raw = raw.tolist()

    if not isinstance(raw, list) or not raw:
      raise ValueError(f"Unexpected embedding response of type {type(raw).__name__}")

    # Unwrap a single-item batch: [[...]] -> [...]
    while isinstance(raw[0], list) and len(raw) == 1:
      raw = raw[0]

    if isinstance(raw[0], list):
      # Token-level vectors — mean-pool into one sentence vector
      width = len(raw[0])
      pooled = [sum(row[i] for row in raw) / len(raw) for i in range(width)]
      return [float(x) for x in pooled]

    return [float(x) for x in raw]

  @classmethod
  def embed_text(cls, text: str) -> list[float]:
    """Embed a single string, returning EMBED_DIMENSIONS floats."""
    logger.debug("[hf] embed model=%s input_len=%d", cls.embed_model, len(text or ""))
    raw = cls.client.feature_extraction(text or "", model=cls.embed_model)
    vector = cls._to_float_list(raw)
    if len(vector) != EMBED_DIMENSIONS:
      logger.warning(
        "[hf] model %s returned %d dimensions, expected %d",
        cls.embed_model, len(vector), EMBED_DIMENSIONS,
      )
    return vector

  @classmethod
  def embed_texts(cls, texts) -> list[list[float]]:
    """Embed several strings, preserving order.

    The Inference API's feature_extraction takes one input at a time, so this
    is a loop rather than a true batch — unlike OllamaConnector.embed_texts,
    which sent one request for the whole batch. Callers on the per-message
    indexing path will make one HTTP round trip per chunk.
    """
    texts = list(texts)
    if not texts:
      return []
    return [cls.embed_text(text) for text in texts]
