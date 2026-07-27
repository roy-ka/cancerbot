"""Security regression tests.

These pin down fixes that are silent when they regress — an SSRF guard that
stops resolving DNS, a fetch that starts following redirects again, or a log
line that starts emitting password-reset links in production all keep working
from the user's point of view while reopening the hole.

Covers:
- SSRF: literal private IPs, DNS names resolving to private space, redirects
  into private space, and the `req.urls` entry point that used to skip the
  check entirely
- Response size caps on untrusted fetches
- NLP service input length cap
- X-Forwarded-For no longer defeating per-IP rate limits
- is_prod() gating of reset/verification link logging
"""
import ipaddress
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.routers.conversation_helper import (
    _MAX_FETCH_BYTES,
    _MAX_REDIRECTS,
    _is_blocked_address,
    _is_safe_url,
    _safe_get,
    _validate_fetch_target,
    fetch_url_contents,
)


# ---------------------------------------------------------------------------
# Address classification
# ---------------------------------------------------------------------------

class TestBlockedAddresses:
    @pytest.mark.parametrize("addr", [
        "127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1",
        "169.254.169.254",          # cloud instance metadata
        "0.0.0.0", "100.64.1.1",    # CGNAT
        "224.0.0.1", "240.0.0.1",
        "::1", "fc00::1", "fe80::1",
        "::ffff:127.0.0.1",         # IPv4-mapped loopback
    ])
    def test_non_public_addresses_are_blocked(self, addr):
        assert _is_blocked_address(ipaddress.ip_address(addr)) is True

    @pytest.mark.parametrize("addr", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700::1111"])
    def test_public_addresses_are_allowed(self, addr):
        assert _is_blocked_address(ipaddress.ip_address(addr)) is False


class TestIsSafeUrl:
    @pytest.mark.parametrize("url", [
        "http://127.0.0.1:8000/health",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:9200",
        "ftp://example.com/x",
        "file:///etc/passwd",
        "javascript:alert(1)",
    ])
    def test_rejects_obvious_targets(self, url):
        assert _is_safe_url(url) is False

    def test_hostnames_pass_the_cheap_filter_only(self):
        """_is_safe_url cannot resolve DNS, so a hostname passes here — which is
        exactly why _validate_fetch_target must be the gate before any fetch."""
        assert _is_safe_url("http://nlp-service:8100/health") is True


# ---------------------------------------------------------------------------
# DNS-resolving validator
# ---------------------------------------------------------------------------

class TestValidateFetchTarget:
    @pytest.mark.asyncio
    async def test_hostname_resolving_to_loopback_is_blocked(self, monkeypatch):
        monkeypatch.setattr(
            "src.routers.conversation_helper._resolve_host", lambda h, p: ["127.0.0.1"]
        )
        assert await _validate_fetch_target("http://evil.example.com/") is False

    @pytest.mark.asyncio
    async def test_internal_service_name_is_blocked(self, monkeypatch):
        monkeypatch.setattr(
            "src.routers.conversation_helper._resolve_host", lambda h, p: ["172.30.0.5"]
        )
        assert await _validate_fetch_target("http://nlp-service:8100/health") is False

    @pytest.mark.asyncio
    async def test_metadata_endpoint_by_name_is_blocked(self, monkeypatch):
        monkeypatch.setattr(
            "src.routers.conversation_helper._resolve_host", lambda h, p: ["169.254.169.254"]
        )
        assert await _validate_fetch_target("http://metadata.google.internal/") is False

    @pytest.mark.asyncio
    async def test_blocked_when_any_resolved_address_is_private(self, monkeypatch):
        """A name answering with both a public and a private address must not
        slip through on the strength of the public one."""
        monkeypatch.setattr(
            "src.routers.conversation_helper._resolve_host",
            lambda h, p: ["93.184.216.34", "127.0.0.1"],
        )
        assert await _validate_fetch_target("http://mixed.example.com/") is False

    @pytest.mark.asyncio
    async def test_unresolvable_host_is_blocked(self, monkeypatch):
        monkeypatch.setattr("src.routers.conversation_helper._resolve_host", lambda h, p: [])
        assert await _validate_fetch_target("http://nx.example.com/") is False

    @pytest.mark.asyncio
    async def test_public_hostname_is_allowed(self, monkeypatch):
        monkeypatch.setattr(
            "src.routers.conversation_helper._resolve_host", lambda h, p: ["93.184.216.34"]
        )
        assert await _validate_fetch_target("https://example.com/article") is True

    @pytest.mark.asyncio
    async def test_literal_public_ip_needs_no_resolution(self, monkeypatch):
        def _boom(host, port):
            raise AssertionError("should not resolve a literal IP")
        monkeypatch.setattr("src.routers.conversation_helper._resolve_host", _boom)
        assert await _validate_fetch_target("http://93.184.216.34/") is True


# ---------------------------------------------------------------------------
# _safe_get — redirects and size caps
# ---------------------------------------------------------------------------

def _client_returning(responses):
    """AsyncClient stub whose .stream() yields the queued responses in order."""
    calls = list(responses)

    class _Ctx:
        def __init__(self, resp):
            self._resp = resp

        async def __aenter__(self):
            return self._resp

        async def __aexit__(self, *exc):
            return False

    client = MagicMock()
    client.stream = MagicMock(side_effect=lambda *a, **k: _Ctx(calls.pop(0)))
    return client


def _response(status=200, headers=None, body=b"hello", url="https://example.com/"):
    resp = httpx.Response(status_code=status, headers=headers or {}, request=httpx.Request("GET", url))

    async def _aiter():
        yield body

    resp.aiter_bytes = lambda: _aiter()
    return resp


class TestSafeGet:
    @pytest.mark.asyncio
    async def test_redirect_into_private_space_is_blocked(self, monkeypatch):
        """The classic bypass: a public URL 302s to the metadata endpoint."""
        def _resolve(host, port):
            return ["93.184.216.34"] if host == "example.com" else ["169.254.169.254"]
        monkeypatch.setattr("src.routers.conversation_helper._resolve_host", _resolve)

        redirect = _response(status=302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
        client = _client_returning([redirect])

        assert await _safe_get(client, "https://example.com/") is None

    @pytest.mark.asyncio
    async def test_redirect_to_public_target_is_followed(self, monkeypatch):
        monkeypatch.setattr(
            "src.routers.conversation_helper._resolve_host", lambda h, p: ["93.184.216.34"]
        )
        redirect = _response(status=302, headers={"location": "https://example.com/final"})
        final = _response(status=200, body=b"final body")
        client = _client_returning([redirect, final])

        resp = await _safe_get(client, "https://example.com/")
        assert resp is not None
        assert resp.content == b"final body"

    @pytest.mark.asyncio
    async def test_redirect_loop_gives_up(self, monkeypatch):
        monkeypatch.setattr(
            "src.routers.conversation_helper._resolve_host", lambda h, p: ["93.184.216.34"]
        )
        hops = [
            _response(status=302, headers={"location": f"https://example.com/{i}"})
            for i in range(_MAX_REDIRECTS + 2)
        ]
        client = _client_returning(hops)

        assert await _safe_get(client, "https://example.com/") is None

    @pytest.mark.asyncio
    async def test_oversized_declared_content_length_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            "src.routers.conversation_helper._resolve_host", lambda h, p: ["93.184.216.34"]
        )
        huge = _response(headers={"content-length": str(_MAX_FETCH_BYTES + 1)})
        client = _client_returning([huge])

        assert await _safe_get(client, "https://example.com/") is None

    @pytest.mark.asyncio
    async def test_body_exceeding_cap_is_aborted(self, monkeypatch):
        """No content-length header — the cap must still apply while streaming."""
        monkeypatch.setattr(
            "src.routers.conversation_helper._resolve_host", lambda h, p: ["93.184.216.34"]
        )
        oversized = _response(body=b"x" * (_MAX_FETCH_BYTES + 10))
        client = _client_returning([oversized])

        assert await _safe_get(client, "https://example.com/") is None

    @pytest.mark.asyncio
    async def test_normal_response_passes_through(self, monkeypatch):
        monkeypatch.setattr(
            "src.routers.conversation_helper._resolve_host", lambda h, p: ["93.184.216.34"]
        )
        client = _client_returning([_response(body=b"<html>ok</html>")])

        resp = await _safe_get(client, "https://example.com/")
        assert resp is not None
        assert resp.content == b"<html>ok</html>"


# ---------------------------------------------------------------------------
# The entry point that used to skip validation entirely
# ---------------------------------------------------------------------------

class TestFetchUrlContentsGate:
    @pytest.mark.asyncio
    async def test_req_urls_path_cannot_reach_private_addresses(self, monkeypatch):
        """`req.urls` is validated only for its scheme by the request model, so
        fetch_url_contents itself has to refuse non-public targets.

        _safe_get is stubbed to *succeed* with real-looking content: asserting
        only on an empty result would pass even without the gate, because a
        genuine request to a metadata address fails on its own in CI. The point
        is that the fetch is never attempted at all.
        """
        monkeypatch.setattr(
            "src.routers.conversation_helper._resolve_host", lambda h, p: ["169.254.169.254"]
        )
        enqueue = MagicMock()
        monkeypatch.setattr("src.routers.conversation_helper._enqueue_url_classification", enqueue)

        would_have_leaked = AsyncMock(return_value=_response(body=b"<html>AWS_SECRET_KEY</html>"))
        monkeypatch.setattr("src.routers.conversation_helper._safe_get", would_have_leaked)

        results = await fetch_url_contents([
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
            "http://127.0.0.1:8000/health",
        ])

        would_have_leaked.assert_not_awaited()
        assert results == []
        enqueue.assert_not_called()

    @pytest.mark.asyncio
    async def test_blocked_url_is_never_fetched(self, monkeypatch):
        """Nothing should even hit the network for a blocked target."""
        monkeypatch.setattr(
            "src.routers.conversation_helper._resolve_host", lambda h, p: ["127.0.0.1"]
        )
        safe_get = AsyncMock(return_value=None)
        monkeypatch.setattr("src.routers.conversation_helper._safe_get", safe_get)

        assert await fetch_url_contents(["http://internal.example.com/secrets"]) == []
        safe_get.assert_not_awaited()


# ---------------------------------------------------------------------------
# NLP service input cap
# ---------------------------------------------------------------------------

class TestNlpInputCap:
    """The NLP service has no auth of its own and a scispaCy parse is CPU-bound,
    so an unbounded `text` field is a denial-of-service primitive.

    app.py can't be imported here — it loads the spaCy pipeline at module scope
    — so the real module is compiled and its class definitions inspected
    instead of re-declaring a lookalike model, which would assert nothing about
    the shipped service.
    """

    def _app_module_ast(self):
        import ast, pathlib

        source = (pathlib.Path(__file__).resolve().parent.parent / "nlp_service" / "app.py").read_text()
        return ast.parse(source), source

    def test_both_request_models_bound_their_text_field(self):
        import ast

        tree, _ = self._app_module_ast()
        bounded = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name not in ("ExtractReq", "SpellingReq"):
                continue
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and getattr(stmt.target, "id", None) == "text"
                    and isinstance(stmt.value, ast.Call)
                    and any(kw.arg == "max_length" for kw in stmt.value.keywords)
                ):
                    bounded.add(node.name)

        assert bounded == {"ExtractReq", "SpellingReq"}, (
            f"unbounded text field on: {{'ExtractReq', 'SpellingReq'}} - {bounded}"
        )

    def test_cap_is_a_sane_value(self):
        import ast

        tree, _ = self._app_module_ast()
        cap = next(
            (
                node.value.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "MAX_TEXT_CHARS" for t in node.targets)
                and isinstance(node.value, ast.Constant)
            ),
            None,
        )
        assert cap is not None, "MAX_TEXT_CHARS is not defined"
        # Above the 4000-char API message limit, well below a DoS-sized body
        assert 4_000 < cap <= 100_000


# ---------------------------------------------------------------------------
# Rate-limit source address
# ---------------------------------------------------------------------------

class TestClientIpTrust:
    def _request(self, headers, peer):
        req = MagicMock()
        req.headers = headers
        req.client = MagicMock()
        req.client.host = peer
        return req

    def test_forwarded_header_is_ignored(self):
        from src.routers.auth import _client_ip

        req = self._request({"X-Forwarded-For": "1.2.3.4"}, "203.0.113.9")
        assert _client_ip(req) == "203.0.113.9"

    def test_spoofed_header_cannot_rotate_the_rate_limit_key(self):
        from src.routers.auth import _client_ip

        peers = {
            _client_ip(self._request({"X-Forwarded-For": f"10.0.0.{i}"}, "203.0.113.9"))
            for i in range(20)
        }
        assert peers == {"203.0.113.9"}

    def test_missing_client_is_handled(self):
        from src.routers.auth import _client_ip

        req = MagicMock()
        req.headers = {}
        req.client = None
        assert _client_ip(req) == "unknown"


# ---------------------------------------------------------------------------
# Production detection for link logging
# ---------------------------------------------------------------------------

class TestResetLinkLogging:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("env", ["prod", "production", "PROD", "Production"])
    async def test_links_are_not_logged_in_any_production_spelling(self, env, monkeypatch, caplog):
        """email.py used to compare ENV != "production" while everything else
        used is_prod(), which also accepts "prod" — so ENV=prod logged live
        password-reset links straight to the shipping log handler."""
        import src.utils.email as email_module

        monkeypatch.setattr(email_module, "is_prod", lambda: env.lower() in ("prod", "production"))
        monkeypatch.setattr(email_module, "_send_sendgrid", MagicMock())

        with caplog.at_level("INFO"):
            await email_module.send_password_reset_email(
                to="user@example.com", name="User", link="https://app/reset?token=SECRET123"
            )

        assert "SECRET123" not in caplog.text

    @pytest.mark.asyncio
    async def test_links_still_logged_in_development(self, monkeypatch, caplog):
        import src.utils.email as email_module

        monkeypatch.setattr(email_module, "is_prod", lambda: False)
        monkeypatch.setattr(email_module, "_send_sendgrid", MagicMock())

        with caplog.at_level("INFO"):
            await email_module.send_password_reset_email(
                to="user@example.com", name="User", link="https://app/reset?token=DEVTOKEN"
            )

        assert "DEVTOKEN" in caplog.text
