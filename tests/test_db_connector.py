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
        monkeypatch.setenv("OPENSEARCH_VERIFY_CERTS", "false")
        monkeypatch.setattr(dbConnector, "_PASS", "fake-password")
        monkeypatch.setattr("src.retrieval.db_connector.model_name", "nomic-embed-text")
        monkeypatch.setattr("src.retrieval.db_connector.is_prod", lambda: False)

        with patch("src.retrieval.db_connector.OpenSearch") as mock_os:
            dbConnector._initialize()

        _, kwargs = mock_os.call_args
        assert kwargs.get("verify_certs") is False
        assert "ssl_context" not in kwargs
