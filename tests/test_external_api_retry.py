"""Tests for retry logic on PubMed, CrossRef, and Wikipedia API calls."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
import httpx

from src.routers.conversation_helper import (
    _retry_get,
    _search_pubmed_sources,
    _search_crossref_sources,
    _wiki_search,
    _RETRY_MAX,
)


def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
    return resp


# ---------------------------------------------------------------------------
# _retry_get
# ---------------------------------------------------------------------------

class TestRetryGet:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response(200)
        resp = await _retry_get(client, "https://example.com")
        assert resp.status_code == 200
        client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_retries_on_500_then_succeeds(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [
            _mock_response(500),
            _mock_response(200),
        ]
        with patch("src.routers.conversation_helper.asyncio.sleep", new_callable=AsyncMock):
            resp = await _retry_get(client, "https://example.com", retries=2)
        assert resp.status_code == 200
        assert client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_429_then_succeeds(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [
            _mock_response(429),
            _mock_response(200),
        ]
        with patch("src.routers.conversation_helper.asyncio.sleep", new_callable=AsyncMock):
            resp = await _retry_get(client, "https://example.com", retries=2)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_retries_on_timeout_then_succeeds(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [
            httpx.TimeoutException("timed out"),
            _mock_response(200),
        ]
        with patch("src.routers.conversation_helper.asyncio.sleep", new_callable=AsyncMock):
            resp = await _retry_get(client, "https://example.com", retries=2)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = httpx.TimeoutException("timed out")
        with patch("src.routers.conversation_helper.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.TimeoutException):
                await _retry_get(client, "https://example.com", retries=3)
        assert client.get.call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_404(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response(404)
        resp = await _retry_get(client, "https://example.com", retries=3)
        assert resp.status_code == 404
        client.get.assert_called_once()


# ---------------------------------------------------------------------------
# _search_pubmed_sources
# ---------------------------------------------------------------------------

class TestPubmedRetry:
    @pytest.mark.asyncio
    async def test_returns_empty_on_persistent_failure(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = httpx.TimeoutException("timeout")
        with patch("src.routers.conversation_helper.asyncio.sleep", new_callable=AsyncMock):
            result = await _search_pubmed_sources(client, ["cancer"])
        assert result == []
        assert client.get.call_count == _RETRY_MAX

    @pytest.mark.asyncio
    async def test_returns_empty_on_esearch_500(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response(500)
        with patch("src.routers.conversation_helper.asyncio.sleep", new_callable=AsyncMock):
            result = await _search_pubmed_sources(client, ["cancer"])
        assert result == []


# ---------------------------------------------------------------------------
# _search_crossref_sources
# ---------------------------------------------------------------------------

class TestCrossrefRetry:
    @pytest.mark.asyncio
    async def test_returns_empty_on_persistent_timeout(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = httpx.TimeoutException("timeout")
        with patch("src.routers.conversation_helper.asyncio.sleep", new_callable=AsyncMock):
            result = await _search_crossref_sources(client, ["cancer"])
        assert result == []
        assert client.get.call_count == _RETRY_MAX

    @pytest.mark.asyncio
    async def test_succeeds_after_one_retry(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        ok_resp = _mock_response(200, json_data={
            "message": {
                "items": [{
                    "DOI": "10.1234/test",
                    "title": ["Cancer treatment study"],
                    "abstract": "An abstract about cancer treatment.",
                    "URL": "https://doi.org/10.1234/test",
                }]
            }
        })
        client.get.side_effect = [httpx.TimeoutException("timeout"), ok_resp]
        with patch("src.routers.conversation_helper.asyncio.sleep", new_callable=AsyncMock):
            result = await _search_crossref_sources(client, ["cancer"])
        assert len(result) == 1
        assert result[0]["doi"] == "10.1234/test"


# ---------------------------------------------------------------------------
# _wiki_search
# ---------------------------------------------------------------------------

class TestWikiSearchRetry:
    def test_returns_results_on_first_attempt(self):
        ok_resp = _mock_response(200, json_data={"query": {"search": [{"title": "Cancer"}]}})
        with patch("httpx.get", return_value=ok_resp):
            result = _wiki_search("cancer")
        assert result == [{"title": "Cancer"}]

    def test_retries_on_timeout_then_succeeds(self):
        ok_resp = _mock_response(200, json_data={"query": {"search": [{"title": "Cancer"}]}})
        with patch("httpx.get", side_effect=[httpx.TimeoutException("timeout"), ok_resp]), \
             patch("src.routers.conversation_helper.time.sleep"):
            result = _wiki_search("cancer")
        assert result == [{"title": "Cancer"}]

    def test_returns_empty_after_all_retries(self):
        with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")), \
             patch("src.routers.conversation_helper.time.sleep"):
            result = _wiki_search("cancer")
        assert result == []

    def test_retries_on_503(self):
        ok_resp = _mock_response(200, json_data={"query": {"search": [{"title": "Tumor"}]}})
        with patch("httpx.get", side_effect=[_mock_response(503), ok_resp]), \
             patch("src.routers.conversation_helper.time.sleep"):
            result = _wiki_search("tumor")
        assert result == [{"title": "Tumor"}]

    def test_no_retry_on_non_transient_exception(self):
        with patch("httpx.get", side_effect=ValueError("unexpected")), \
             patch("src.routers.conversation_helper.time.sleep") as mock_sleep:
            result = _wiki_search("cancer")
        assert result == []
        mock_sleep.assert_not_called()

    def test_uses_shared_client_when_provided(self):
        """When a client is passed (the pooled _fetch path), the call routes
        through client.get for connection reuse, not the module-level httpx.get."""
        client = MagicMock()
        client.get.return_value = _mock_response(200, json_data={"query": {"search": [{"title": "Cancer"}]}})
        with patch("httpx.get") as module_get:
            result = _wiki_search("cancer", client=client)
        assert result == [{"title": "Cancer"}]
        client.get.assert_called_once()
        module_get.assert_not_called()
