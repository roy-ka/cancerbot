"""Regression tests for the per-request resource optimizations.

Each test here pins down a property that keeps the chat path cheap. They are
easy to undo by accident — a stray `_source: True`, a loop that goes back to
one query per message, or a per-chunk index call all still *work*, they just
cost far more CPU, RAM and network than they need to.

Covers:
- OpenSearch responses never ship the 768-float `embedding` array
- Per-message source lookups are batched into one query
- Chunks are embedded and indexed in bulk, refreshing once
- NLP extraction happens once per message, not twice
- is_exist() stays pandas-free
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.retrieval.db_connector import dbConnector
from src.retrieval.search import search_sources


# ---------------------------------------------------------------------------
# _source allowlists — no embedding vectors in responses
# ---------------------------------------------------------------------------

class TestSourceFieldAllowlists:
    def test_search_sources_excludes_embedding_from_source(self):
        db = MagicMock()
        empty = {"hits": {"hits": [], "total": {"value": 0}}}
        # Hybrid retrieval issues the dense and lexical halves as one msearch
        db.msearch.return_value = [empty, empty]

        search_sources(db, text="glioblastoma", vector=[0.1, 0.2])

        _, kwargs = db.msearch.call_args
        bodies = kwargs["bodies"]
        assert len(bodies) == 2
        for body in bodies:
            source_fields = body["_source"]
            assert "embedding" not in source_fields
            # The prompt builder still needs these two
            assert "content_for_embedding" in source_fields
            assert "id" in source_fields

    def test_hybrid_search_costs_one_round_trip(self):
        """Two ranked lists are needed for rank fusion, but they must not cost
        two sequential OpenSearch round trips on every chat message."""
        db = MagicMock()
        empty = {"hits": {"hits": [], "total": {"value": 0}}}
        db.msearch.return_value = [empty, empty]

        search_sources(db, text="glioblastoma", vector=[0.1, 0.2])

        # Both sub-queries ride in a single msearch call
        assert db.msearch.call_count == 1
        assert len(db.msearch.call_args.kwargs["bodies"]) == 2

    def test_get_claims_and_sources_requests_only_display_fields(self, monkeypatch):
        client = MagicMock()
        client.search.return_value = {"hits": {"hits": []}}
        monkeypatch.setattr(dbConnector, "_initialize", classmethod(lambda cls: None))
        monkeypatch.setattr(dbConnector, "db_client", client)
        monkeypatch.setattr(dbConnector, "_model", {"sources_index": "sources"})

        dbConnector.get_claims_and_sources_by_id(["pmid:1:c0", "pmid:2"])

        body = client.search.call_args.kwargs["body"]
        assert body["_source"] == dbConnector.SOURCE_DISPLAY_FIELDS
        assert "embedding" not in body["_source"]
        # full_text is what the UI renders as the source excerpt
        assert "full_text" in body["_source"]

    def test_get_claims_and_sources_scales_size_to_id_count(self, monkeypatch):
        client = MagicMock()
        client.search.return_value = {"hits": {"hits": []}}
        monkeypatch.setattr(dbConnector, "_initialize", classmethod(lambda cls: None))
        monkeypatch.setattr(dbConnector, "db_client", client)
        monkeypatch.setattr(dbConnector, "_model", {"sources_index": "sources"})

        dbConnector.get_claims_and_sources_by_id(["pmid:1:c0", "pmid:2:c0"])
        small = client.search.call_args.kwargs["body"]["size"]

        dbConnector.get_claims_and_sources_by_id([f"pmid:{i}" for i in range(50)])
        large = client.search.call_args.kwargs["body"]["size"]

        assert small < large
        assert large <= 200  # still bounded


# ---------------------------------------------------------------------------
# Batched per-message source lookups
# ---------------------------------------------------------------------------

def _hit(base_id, title, index="sources"):
    return {
        "_index": index,
        "_source": {"id": f"{base_id}:c0", "source_id": base_id, "title": title,
                    "url": f"https://example.org/{base_id}", "source_type": "pubmed",
                    "full_text": f"text for {base_id}"},
    }


class TestBulkClaimsAndSources:
    def test_many_messages_cost_one_opensearch_query(self, monkeypatch):
        from src.db.repositories.messeges import add_claims_and_sources_bulk

        messages = []
        for i in range(5):
            m = MagicMock()
            m.sources_ids = [f"pmid:{i}"]
            m.role = "assistant"
            messages.append(m)

        fake_get = MagicMock(return_value={"hits": {"hits": [_hit(f"pmid:{i}", f"T{i}") for i in range(5)]}})
        monkeypatch.setattr(dbConnector, "get_claims_and_sources_by_id", fake_get)

        add_claims_and_sources_bulk(messages)

        assert fake_get.call_count == 1

    def test_each_message_gets_only_its_own_sources(self, monkeypatch):
        from src.db.repositories.messeges import add_claims_and_sources_bulk

        first, second = MagicMock(), MagicMock()
        first.sources_ids = ["pmid:1"]
        second.sources_ids = ["pmid:2"]

        monkeypatch.setattr(
            dbConnector,
            "get_claims_and_sources_by_id",
            MagicMock(return_value={"hits": {"hits": [_hit("pmid:1", "One"), _hit("pmid:2", "Two")]}}),
        )

        add_claims_and_sources_bulk([first, second])

        assert [s["id"] for s in first.sources] == ["pmid:1"]
        assert [s["id"] for s in second.sources] == ["pmid:2"]

    def test_chunks_of_one_source_collapse_to_a_single_entry(self, monkeypatch):
        from src.db.repositories.messeges import add_claims_and_sources_bulk

        message = MagicMock()
        message.sources_ids = ["pmid:1"]
        hits = [_hit("pmid:1", "One"), _hit("pmid:1", "One")]
        hits[1]["_source"]["id"] = "pmid:1:c1"
        monkeypatch.setattr(
            dbConnector, "get_claims_and_sources_by_id", MagicMock(return_value={"hits": {"hits": hits}})
        )

        add_claims_and_sources_bulk([message])

        assert len(message.sources) == 1

    def test_messages_without_sources_are_skipped_entirely(self, monkeypatch):
        from src.db.repositories.messeges import add_claims_and_sources_bulk

        message = MagicMock()
        message.sources_ids = None
        fake_get = MagicMock()
        monkeypatch.setattr(dbConnector, "get_claims_and_sources_by_id", fake_get)

        add_claims_and_sources_bulk([message])

        fake_get.assert_not_called()

    def test_opensearch_failure_leaves_messages_untouched(self, monkeypatch):
        from src.db.repositories.messeges import add_claims_and_sources_bulk

        message = MagicMock()
        message.sources_ids = ["pmid:1"]
        monkeypatch.setattr(
            dbConnector, "get_claims_and_sources_by_id", MagicMock(side_effect=RuntimeError("down"))
        )

        add_claims_and_sources_bulk([message])  # must not raise

    def test_legacy_csv_sources_ids_still_resolve(self, monkeypatch):
        from src.db.repositories.messeges import add_claims_and_sources_bulk

        message = MagicMock()
        message.sources_ids = "pmid:1, pmid:2"
        monkeypatch.setattr(
            dbConnector,
            "get_claims_and_sources_by_id",
            MagicMock(return_value={"hits": {"hits": [_hit("pmid:1", "One"), _hit("pmid:2", "Two")]}}),
        )

        add_claims_and_sources_bulk([message])

        assert [s["id"] for s in message.sources] == ["pmid:1", "pmid:2"]

    def test_claims_and_sources_are_split_by_index(self, monkeypatch):
        from src.db.repositories.messeges import add_claims_and_sources_bulk

        message = MagicMock()
        message.sources_ids = ["pmid:1", "claim:9"]
        monkeypatch.setattr(
            dbConnector,
            "get_claims_and_sources_by_id",
            MagicMock(return_value={"hits": {"hits": [
                _hit("pmid:1", "One"),
                _hit("claim:9", "A claim", index="v1.5_claims_nomic-embed-text_index"),
            ]}}),
        )

        add_claims_and_sources_bulk([message])

        assert [s["id"] for s in message.sources] == ["pmid:1"]
        assert [c["id"] for c in message.claims] == ["claim:9"]


# ---------------------------------------------------------------------------
# Batched embedding + bulk indexing
# ---------------------------------------------------------------------------

class TestBatchEmbedAndBulkIndex:
    def _db(self):
        db = MagicMock()
        db.existing_base_source_ids.return_value = set()
        db.bulk_index_to_db.side_effect = lambda index_name, docs: (len(list(docs)), [])
        return db

    def test_all_chunks_embedded_in_one_request(self, monkeypatch):
        from src.routers.conversation_helper import _embed_and_index_sources

        db = self._db()
        monkeypatch.setattr("src.routers.conversation_helper.dbConnector", lambda: db)
        source = {
            "source_type": "pubmed", "pmid": "1", "title": "T",
            "content_for_embedding": " ".join(["word"] * 300),
        }

        embed = MagicMock(side_effect=lambda texts: [[0.1] * 768 for _ in texts])
        with patch("src.routers.conversation_helper.OllamaConnector.embed_texts", embed):
            _embed_and_index_sources([source], terms=["cancer"])

        # 300 words → 3 chunks, but a single embedding call
        assert embed.call_count == 1
        assert len(embed.call_args.args[0]) == 3

    def test_all_chunks_written_in_one_bulk_call(self, monkeypatch):
        from src.routers.conversation_helper import _embed_and_index_sources

        db = self._db()
        monkeypatch.setattr("src.routers.conversation_helper.dbConnector", lambda: db)
        sources = [
            {"source_type": "pubmed", "pmid": str(i), "title": "T",
             "content_for_embedding": " ".join(["word"] * 300)}
            for i in range(3)
        ]

        with patch("src.routers.conversation_helper.OllamaConnector.embed_texts",
                   side_effect=lambda texts: [[0.1] * 768 for _ in texts]):
            indexed, _ = _embed_and_index_sources(sources, terms=["cancer"])

        assert db.bulk_index_to_db.call_count == 1
        assert indexed == 9  # 3 sources × 3 chunks

    def test_embedding_failure_counts_all_chunks_as_skipped(self, monkeypatch):
        from src.routers.conversation_helper import _embed_and_index_sources

        db = self._db()
        monkeypatch.setattr("src.routers.conversation_helper.dbConnector", lambda: db)
        source = {"source_type": "pubmed", "pmid": "1", "title": "T",
                  "content_for_embedding": " ".join(["word"] * 300)}

        with patch("src.routers.conversation_helper.OllamaConnector.embed_texts",
                   side_effect=RuntimeError("ollama down")):
            indexed, skipped = _embed_and_index_sources([source], terms=["cancer"])

        assert indexed == 0
        assert skipped == 3
        db.bulk_index_to_db.assert_not_called()

    def test_partial_bulk_failures_are_counted_as_skipped(self, monkeypatch):
        from src.routers.conversation_helper import _embed_and_index_sources

        db = self._db()
        db.bulk_index_to_db.side_effect = lambda index_name, docs: (2, ["boom"])
        monkeypatch.setattr("src.routers.conversation_helper.dbConnector", lambda: db)
        source = {"source_type": "pubmed", "pmid": "1", "title": "T",
                  "content_for_embedding": " ".join(["word"] * 300)}

        with patch("src.routers.conversation_helper.OllamaConnector.embed_texts",
                   side_effect=lambda texts: [[0.1] * 768 for _ in texts]):
            indexed, skipped = _embed_and_index_sources([source], terms=["cancer"])

        assert indexed == 2
        assert skipped == 1

    def test_bulk_index_refreshes_once_for_the_whole_batch(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr(dbConnector, "_initialize", classmethod(lambda cls: None))
        monkeypatch.setattr(dbConnector, "db_client", client)
        monkeypatch.setattr(dbConnector, "_model", {"sources_index": "sources"})

        docs = [{"id": f"pmid:1:c{i}"} for i in range(4)]
        with patch("opensearchpy.helpers.bulk", return_value=(4, [])) as mock_bulk:
            succeeded, errors = dbConnector.bulk_index_to_db("sources_index", docs)

        assert succeeded == 4
        assert errors == []
        assert mock_bulk.call_count == 1
        assert mock_bulk.call_args.kwargs["refresh"] is True

    def test_bulk_index_is_a_noop_for_an_empty_batch(self, monkeypatch):
        monkeypatch.setattr(dbConnector, "_initialize", classmethod(lambda cls: None))
        monkeypatch.setattr(dbConnector, "db_client", MagicMock())
        monkeypatch.setattr(dbConnector, "_model", {"sources_index": "sources"})

        with patch("opensearchpy.helpers.bulk") as mock_bulk:
            assert dbConnector.bulk_index_to_db("sources_index", []) == (0, [])
        mock_bulk.assert_not_called()


class TestEmbedTexts:
    def test_batch_returns_one_vector_per_input(self):
        from src.classes.ollama_connector import OllamaConnector

        response = MagicMock()
        response.embeddings = [[0.1] * 768, [0.2] * 768]
        with patch.object(OllamaConnector, "ollama") as ollama:
            ollama.embed.return_value = response
            out = OllamaConnector.embed_texts(["a", "b"])

        assert out == [[0.1] * 768, [0.2] * 768]
        assert ollama.embed.call_args.kwargs["input"] == ["a", "b"]

    def test_empty_input_makes_no_request(self):
        from src.classes.ollama_connector import OllamaConnector

        with patch.object(OllamaConnector, "ollama") as ollama:
            assert OllamaConnector.embed_texts([]) == []
        ollama.embed.assert_not_called()

    def test_count_mismatch_raises_rather_than_misaligning_vectors(self):
        from src.classes.ollama_connector import OllamaConnector

        response = MagicMock()
        response.embeddings = [[0.1] * 768]
        with patch.object(OllamaConnector, "ollama") as ollama:
            ollama.embed.return_value = response
            with pytest.raises(ValueError):
                OllamaConnector.embed_texts(["a", "b"])


# ---------------------------------------------------------------------------
# create_index caching
# ---------------------------------------------------------------------------

class TestIndexExistenceCaching:
    def test_exists_check_is_not_repeated(self, monkeypatch):
        client = MagicMock()
        client.indices.exists.return_value = True
        monkeypatch.setattr(dbConnector, "_initialize", classmethod(lambda cls: None))
        monkeypatch.setattr(dbConnector, "db_client", client)
        monkeypatch.setattr(dbConnector, "_model", {"sources_index": "sources"})
        monkeypatch.setattr(dbConnector, "_known_indexes", set())

        for _ in range(5):
            dbConnector.create_index("sources_index")

        assert client.indices.exists.call_count == 1


# ---------------------------------------------------------------------------
# One NLP pass per message
# ---------------------------------------------------------------------------

class TestSingleNlpExtraction:
    @pytest.mark.asyncio
    async def test_search_and_embed_returns_the_current_messages_own_terms(self, monkeypatch):
        """search_and_embed must hand back `latest_terms` (this message's own
        extraction) so the request path can persist it instead of running a
        second spell-correct + extract pass over the same text."""
        from src.routers import conversation_helper

        message = MagicMock()
        message.content = "does mebendazole help GBM"
        message.extracted_terms = None
        message.id = "m1"
        conversation = MagicMock()
        conversation.messages = [message]
        conversation.id = "c1"

        monkeypatch.setattr(
            conversation_helper,
            "_extract_term_groups_from_message",
            AsyncMock(return_value=(["mebendazole", "GBM"], [])),
        )
        monkeypatch.setattr(conversation_helper, "_search_pubmed_sources", AsyncMock(return_value=[]))
        monkeypatch.setattr(conversation_helper, "_search_crossref_sources", AsyncMock(return_value=[]))
        monkeypatch.setattr(conversation_helper, "_search_wikipedia_sources", AsyncMock(return_value=[]))
        monkeypatch.setattr(conversation_helper, "_search_clinicaltrials_sources", AsyncMock(return_value=[]))
        monkeypatch.setattr(conversation_helper, "_embed_and_index_sources", lambda *a, **k: (0, 0))

        result = await conversation_helper.search_and_embed(conversation)

        assert result["latest_terms"] == ["mebendazole", "GBM"]


# ---------------------------------------------------------------------------
# is_exist without pandas
# ---------------------------------------------------------------------------

class TestIsExistPandasFree:
    def test_utils_module_holds_no_pandas_reference(self):
        """A module-level pandas import here loads pandas + numpy into every
        backend and worker process — utils is imported by main, auth and
        db_connector."""
        from src.utils import utils

        assert not hasattr(utils, "pd")
        assert not any(
            getattr(value, "__name__", "") == "pandas" for value in vars(utils).values()
        )

    @pytest.mark.parametrize("value", [None, "", "NA", "N/A", "null", "None", 0, float("nan")])
    def test_missing_values_are_false(self, value):
        from src.utils.utils import is_exist

        assert is_exist(value) is False

    @pytest.mark.parametrize("value", ["glioblastoma", "12345", 42, ["a"]])
    def test_real_values_are_true(self, value):
        from src.utils.utils import is_exist

        assert is_exist(value) is True
