"""Tests for the Hugging Face embedding connector.

The API is never called for real here — feature_extraction is stubbed, since
these cover response coercion and wiring, not the remote service.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.classes.embedding_connector import (
    EMBED_DIMENSIONS,
    EMBED_MODEL,
    EmbeddingConnector,
)


class TestModelConfiguration:
    def test_uses_the_specified_model(self):
        assert EMBED_MODEL == "sentence-transformers/all-MiniLM-L6-v2"

    def test_declared_dimensions_match_the_model(self):
        assert EMBED_DIMENSIONS == 384


class TestEmbedText:
    def test_returns_a_flat_list_of_floats(self):
        with patch.object(EmbeddingConnector, "client") as client:
            client.feature_extraction.return_value = [0.5] * 384
            out = EmbeddingConnector.embed_text("glioblastoma")

        assert isinstance(out, list)
        assert len(out) == 384
        assert all(isinstance(x, float) for x in out)

    def test_passes_text_and_model_to_the_api(self):
        with patch.object(EmbeddingConnector, "client") as client:
            client.feature_extraction.return_value = [0.1] * 384
            EmbeddingConnector.embed_text("temozolomide")

        args, kwargs = client.feature_extraction.call_args
        assert args[0] == "temozolomide"
        assert kwargs["model"] == EMBED_MODEL

    def test_numpy_style_response_is_converted(self):
        """The client returns an ndarray for sentence-transformers models."""
        fake_array = MagicMock()
        fake_array.tolist.return_value = [0.25] * 384

        with patch.object(EmbeddingConnector, "client") as client:
            client.feature_extraction.return_value = fake_array
            out = EmbeddingConnector.embed_text("text")

        assert out == [0.25] * 384

    def test_single_item_batch_is_unwrapped(self):
        with patch.object(EmbeddingConnector, "client") as client:
            client.feature_extraction.return_value = [[0.75] * 384]
            out = EmbeddingConnector.embed_text("text")

        assert len(out) == 384
        assert out[0] == 0.75

    def test_token_level_output_is_mean_pooled(self):
        """Some models return one vector per token instead of a sentence
        vector; the caller must still get a single vector."""
        with patch.object(EmbeddingConnector, "client") as client:
            client.feature_extraction.return_value = [
                [0.0, 2.0, 4.0],
                [2.0, 4.0, 6.0],
            ]
            out = EmbeddingConnector.embed_text("text")

        assert out == [1.0, 3.0, 5.0]

    def test_unexpected_response_raises(self):
        with patch.object(EmbeddingConnector, "client") as client:
            client.feature_extraction.return_value = None
            with pytest.raises(ValueError):
                EmbeddingConnector.embed_text("text")

    def test_wrong_dimension_is_logged_not_swallowed(self, caplog):
        with patch.object(EmbeddingConnector, "client") as client:
            client.feature_extraction.return_value = [0.1] * 768
            with caplog.at_level("WARNING"):
                out = EmbeddingConnector.embed_text("text")

        assert len(out) == 768
        assert "768" in caplog.text and "384" in caplog.text

    def test_empty_text_is_sent_as_empty_string(self):
        with patch.object(EmbeddingConnector, "client") as client:
            client.feature_extraction.return_value = [0.0] * 384
            EmbeddingConnector.embed_text(None)

        assert client.feature_extraction.call_args.args[0] == ""


class TestApiKeyHandling:
    def test_missing_key_raises_only_when_the_client_is_used(self, monkeypatch):
        """Importing the module must not require the key — the proxy builds the
        client lazily so tests and unrelated code can import this freely."""
        from src.classes.embedding_connector import _InferenceClientProxy

        monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
        monkeypatch.setattr(_InferenceClientProxy, "_client", None)

        proxy = _InferenceClientProxy()
        with pytest.raises(ValueError, match="HUGGINGFACE_API_KEY"):
            proxy._ensure_client()


class TestOllamaEmbeddingRemoved:
    def test_ollama_connector_no_longer_exposes_embeddings(self):
        """Embeddings moved out of OllamaConnector entirely; it now covers text
        generation only."""
        from src.classes.ollama_connector import OllamaConnector

        assert not hasattr(OllamaConnector, "embed_text")
        assert not hasattr(OllamaConnector, "embed_texts")

    def test_retrieval_embeds_with_the_new_connector(self):
        import src.retrieval as retrieval

        assert retrieval.EmbeddingConnector is EmbeddingConnector
