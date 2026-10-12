import ssl
from unittest.mock import patch, MagicMock

from src.retrieval.db_connector import dbConnector


def _reset():
    dbConnector._initialized = False
    dbConnector.db_client = None
    dbConnector._model = None


class TestOpenSearchTLS:
    def teardown_method(self):
        _reset()

    def test_ca_cert_enables_pinned_verification(self, monkeypatch):
        _reset()
        monkeypatch.setenv("OPENSEARCH_CA_CERT", "/fake/root-ca.pem")
        monkeypatch.setenv("OPENSEARCH_URL", "https://localhost:9200")
        monkeypatch.setattr(dbConnector, "_PASS", "fake-password")
        monkeypatch.setattr("src.retrieval.db_connector.model_name", "nomic-embed-text")

        with patch("src.retrieval.db_connector.OpenSearch") as mock_os, \
             patch("src.retrieval.db_connector.ssl.create_default_context") as mock_ctx:
            mock_ctx.return_value = MagicMock()
            dbConnector._initialize()

        mock_ctx.assert_called_once_with(cafile="/fake/root-ca.pem")
        _, kwargs = mock_os.call_args
        assert kwargs["ssl_context"] is mock_ctx.return_value
        # verify_certs/ssl_assert_hostname/ssl_show_warn are ignored (and warned about)
        # by opensearch-py whenever ssl_context is set — must not be passed alongside it.
        assert "verify_certs" not in kwargs
        assert "ssl_assert_hostname" not in kwargs
        assert "ssl_show_warn" not in kwargs

    def test_prod_without_ca_cert_falls_back_insecurely_with_warning(self, monkeypatch, caplog):
        _reset()
        monkeypatch.delenv("OPENSEARCH_CA_CERT", raising=False)
        monkeypatch.setenv("OPENSEARCH_URL", "https://localhost:9200")
        monkeypatch.setenv("OPENSEARCH_VERIFY_CERTS", "false")
        monkeypatch.setattr(dbConnector, "_PASS", "fake-password")
        monkeypatch.setattr("src.retrieval.db_connector.model_name", "nomic-embed-text")
        monkeypatch.setattr("src.retrieval.db_connector.is_prod", lambda: True)

        with patch("src.retrieval.db_connector.OpenSearch") as mock_os:
            with caplog.at_level("WARNING"):
                dbConnector._initialize()

        assert "OPENSEARCH_CA_CERT" in caplog.text
        _, kwargs = mock_os.call_args
        assert kwargs["ssl_context"].verify_mode == ssl.CERT_NONE

    def test_dev_without_ca_cert_skips_ssl_context(self, monkeypatch):
        _reset()
        monkeypatch.delenv("OPENSEARCH_CA_CERT", raising=False)
        monkeypatch.setenv("OPENSEARCH_URL", "https://localhost:9200")
        monkeypatch.setenv("OPENSEARCH_VERIFY_CERTS", "false")
        monkeypatch.setattr(dbConnector, "_PASS", "fake-password")
        monkeypatch.setattr("src.retrieval.db_connector.model_name", "nomic-embed-text")
        monkeypatch.setattr("src.retrieval.db_connector.is_prod", lambda: False)

        with patch("src.retrieval.db_connector.OpenSearch") as mock_os:
            dbConnector._initialize()

        _, kwargs = mock_os.call_args
        assert kwargs.get("verify_certs") is False
        assert "ssl_context" not in kwargs


class TestOpenSearchPlainHttp:
    """Local development runs OpenSearch over plain HTTP with the security
    plugin off (docker-compose.yml); TLS is production-only."""

    def teardown_method(self):
        _reset()

    def test_http_url_gets_plain_client_without_tls_or_auth(self, monkeypatch):
        _reset()
        monkeypatch.setenv("OPENSEARCH_URL", "http://localhost:9200")
        monkeypatch.setenv("OPENSEARCH_CA_CERT", "/fake/root-ca.pem")
        monkeypatch.setattr("src.retrieval.db_connector.model_name", "nomic-embed-text")

        with patch("src.retrieval.db_connector.OpenSearch") as mock_os, \
             patch("src.retrieval.db_connector.ssl.create_default_context") as mock_ctx:
            dbConnector._initialize()

        _, kwargs = mock_os.call_args
        assert kwargs["use_ssl"] is False
        assert "http_auth" not in kwargs
        assert "ssl_context" not in kwargs
        mock_ctx.assert_not_called()

    def test_http_url_needs_no_admin_password(self, monkeypatch):
        _reset()
        monkeypatch.setenv("OPENSEARCH_URL", "http://localhost:9200")
        monkeypatch.setattr(dbConnector, "_PASS", None)
        monkeypatch.setattr("src.retrieval.db_connector.model_name", "nomic-embed-text")

        with patch("src.retrieval.db_connector.OpenSearch") as mock_os:
            dbConnector._initialize()

        mock_os.assert_called_once()

    def test_https_url_still_requires_admin_password(self, monkeypatch):
        _reset()
        monkeypatch.setenv("OPENSEARCH_URL", "https://localhost:9200")
        monkeypatch.setattr(dbConnector, "_PASS", None)
        monkeypatch.setattr("src.retrieval.db_connector.model_name", "nomic-embed-text")

        with patch("src.retrieval.db_connector.OpenSearch") as mock_os:
            dbConnector._initialize()

        mock_os.assert_not_called()


class TestExistingDoiBaseIds:
    """Best-effort DOI-to-source_id lookup used to prevent double-indexing
    the same real article under two different base_id schemes (e.g.
    pmid:X from PubMed and doi:Y from CrossRef) — see
    conversation_helper.py's _embed_and_index_sources."""

    def teardown_method(self):
        _reset()

    def test_returns_empty_dict_for_no_dois(self):
        _reset()
        assert dbConnector.existing_doi_base_ids(set()) == {}

    def test_returns_empty_dict_when_client_unavailable(self):
        _reset()
        dbConnector._initialized = True
        dbConnector.db_client = None
        assert dbConnector.existing_doi_base_ids({"10.1/x"}) == {}

    def test_maps_doi_to_source_id(self):
        _reset()
        dbConnector._initialized = True
        dbConnector._model = {"sources_index": "sources_v1"}
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "hits": {"hits": [
                {"_source": {"doi": "10.1/abc", "source_id": "pmid:123", "id": "pmid:123:c0"}},
            ]}
        }
        dbConnector.db_client = mock_client

        assert dbConnector.existing_doi_base_ids({"10.1/abc"}) == {"10.1/abc": "pmid:123"}

    def test_falls_back_to_stripped_id_when_source_id_missing(self):
        """Legacy pre-chunked-schema docs (see backfill_chunks.py) have no
        source_id field — fall back to the :cN-stripped id, same as
        existing_base_source_ids."""
        _reset()
        dbConnector._initialized = True
        dbConnector._model = {"sources_index": "sources_v1"}
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "hits": {"hits": [
                {"_source": {"doi": "10.1/abc", "id": "doi:10.1/abc:c0"}},
            ]}
        }
        dbConnector.db_client = mock_client

        assert dbConnector.existing_doi_base_ids({"10.1/abc"}) == {"10.1/abc": "doi:10.1/abc"}

    def test_ignores_hits_whose_doi_is_not_in_the_requested_set(self):
        """The match query is analyzed-text matching, not exact — a stray
        hit must not be trusted just because it came back in the results."""
        _reset()
        dbConnector._initialized = True
        dbConnector._model = {"sources_index": "sources_v1"}
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "hits": {"hits": [
                {"_source": {"doi": "10.1/unrelated", "source_id": "pmid:999", "id": "pmid:999:c0"}},
            ]}
        }
        dbConnector.db_client = mock_client

        assert dbConnector.existing_doi_base_ids({"10.1/abc"}) == {}

    def test_query_is_a_match_not_terms_per_doi(self):
        """doi is mapped as analyzed text, not keyword, in the live index —
        an exact terms lookup is unreliable there (see CLAUDE.md)."""
        _reset()
        dbConnector._initialized = True
        dbConnector._model = {"sources_index": "sources_v1"}
        mock_client = MagicMock()
        mock_client.search.return_value = {"hits": {"hits": []}}
        dbConnector.db_client = mock_client

        dbConnector.existing_doi_base_ids({"10.1/abc"})

        body = mock_client.search.call_args.kwargs["body"]
        should = body["query"]["bool"]["should"]
        assert should == [{"match": {"doi": {"query": "10.1/abc", "operator": "and"}}}]
