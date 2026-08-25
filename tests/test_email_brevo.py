import pytest
from unittest.mock import patch, MagicMock

from src.utils.email_brevo import _send_brevo, _BREVO_API_URL, _FROM_EMAIL, _FROM_NAME


def _ok_response():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    return resp


class TestDevMode:
    def test_does_not_call_requests_outside_prod(self, monkeypatch):
        import src.utils.email_brevo as mod
        monkeypatch.setattr(mod, "is_prod", lambda: False)
        monkeypatch.setenv("BREVO_API_KEY", "unused-in-dev")

        with patch("src.utils.email_brevo.requests.post") as mock_post:
            _send_brevo("a@b.c", "Subject", "<p>hi</p>")
            mock_post.assert_not_called()

    def test_logs_recipient_and_subject_not_html(self, monkeypatch, caplog):
        import src.utils.email_brevo as mod
        monkeypatch.setattr(mod, "is_prod", lambda: False)

        with caplog.at_level("INFO"):
            _send_brevo("a@b.c", "Reset your password", "<p>very long html body</p>")

        assert "a@b.c" in caplog.text
        assert "Reset your password" in caplog.text
        assert "very long html body" not in caplog.text


class TestProdSend:
    def test_noop_without_api_key(self, monkeypatch):
        import src.utils.email_brevo as mod
        monkeypatch.setattr(mod, "is_prod", lambda: True)
        monkeypatch.delenv("BREVO_API_KEY", raising=False)

        with patch("src.utils.email_brevo.requests.post") as mock_post:
            _send_brevo("a@b.c", "Subject", "<p>hi</p>")
            mock_post.assert_not_called()

    def test_sends_expected_payload_shape(self, monkeypatch):
        import src.utils.email_brevo as mod
        monkeypatch.setattr(mod, "is_prod", lambda: True)
        monkeypatch.setenv("BREVO_API_KEY", "sekret-key")

        with patch("src.utils.email_brevo.requests.post") as mock_post:
            mock_post.return_value = _ok_response()

            _send_brevo("user@example.com", "Hello", "<p>Body</p>")

            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert args[0] == _BREVO_API_URL
            assert kwargs["headers"]["api-key"] == "sekret-key"
            assert kwargs["timeout"] == 10

            body = kwargs["json"]
            assert body["sender"] == {"email": _FROM_EMAIL, "name": _FROM_NAME}
            assert body["to"] == [{"email": "user@example.com"}]
            assert body["subject"] == "Hello"
            assert body["htmlContent"] == "<p>Body</p>"

    def test_raises_on_http_error(self, monkeypatch):
        """Low-level call raises on purpose — _deliver in email.py is the layer
        that decides a failure must not propagate out of a background task."""
        import src.utils.email_brevo as mod
        monkeypatch.setattr(mod, "is_prod", lambda: True)
        monkeypatch.setenv("BREVO_API_KEY", "sekret-key")

        with patch("src.utils.email_brevo.requests.post") as mock_post:
            resp = MagicMock()
            resp.raise_for_status.side_effect = Exception("HTTP 401: Unauthorized")
            mock_post.return_value = resp

            with pytest.raises(Exception, match="401"):
                _send_brevo("a@b.c", "Subject", "<p>hi</p>")

    def test_raises_on_network_error(self, monkeypatch):
        import src.utils.email_brevo as mod
        monkeypatch.setattr(mod, "is_prod", lambda: True)
        monkeypatch.setenv("BREVO_API_KEY", "sekret-key")

        with patch("src.utils.email_brevo.requests.post") as mock_post:
            mock_post.side_effect = ConnectionError("offline")

            with pytest.raises(ConnectionError):
                _send_brevo("a@b.c", "Subject", "<p>hi</p>")
