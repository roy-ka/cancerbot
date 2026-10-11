"""/health/ must report failure through the HTTP status itself — Docker's
healthcheck (docker-compose.yml) and any external monitor only look at the
status code, not the JSON body."""
from unittest.mock import patch


class TestHealthCheck:
    @patch("src.classes.ollama_connector.OllamaConnector.ollama")
    def test_all_services_up_returns_200(self, mock_ollama, anon_client):
        mock_ollama.list.return_value = {"models": [{"name": "nomic-embed-text"}]}
        response = anon_client.get("/health/")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    @patch("src.classes.ollama_connector.OllamaConnector.ollama")
    def test_ollama_down_returns_503(self, mock_ollama, anon_client):
        mock_ollama.list.side_effect = ConnectionError("ollama unreachable")
        response = anon_client.get("/health/")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["ollama"]["status"] == "error"

    @patch("src.classes.ollama_connector.OllamaConnector.ollama")
    def test_no_models_pulled_returns_503(self, mock_ollama, anon_client):
        mock_ollama.list.return_value = {"models": []}
        response = anon_client.get("/health/")
        assert response.status_code == 503
