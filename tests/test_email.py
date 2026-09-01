import pytest
import asyncio
from unittest.mock import patch, MagicMock


@pytest.fixture
def as_prod(monkeypatch):
    """Force the production branch.

    Outside production `_send_brevo` deliberately short-circuits and never
    touches Brevo, so any test that wants to exercise real delivery has to
    opt in. `ENV` is read once at import in src.utils.utils, so patching the
    is_prod reference each module holds is the reliable way to flip this.
    """
    import src.utils.email as email_module
    import src.utils.email_brevo as email_brevo_module
    monkeypatch.setattr(email_module, "is_prod", lambda: True)
    monkeypatch.setattr(email_brevo_module, "is_prod", lambda: True)
    return email_module


def _mock_post_response(status=200):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
    return resp


class TestDevModeDoesNotSend:
    def test_no_brevo_call_outside_production(self, monkeypatch):
        import src.utils.email as email_module
        import src.utils.email_brevo as email_brevo_module
        monkeypatch.setattr(email_module, "is_prod", lambda: False)
        monkeypatch.setattr(email_brevo_module, "is_prod", lambda: False)
        monkeypatch.setenv("BREVO_API_KEY", "looks-real-but-unused")

        with patch("src.utils.email_brevo.requests.post") as mock_post:
            assert asyncio.run(
                email_module.send_password_reset_email(
                    "user@example.com", "User", "https://app/reset-password?token=abc"
                )
            ) is True
            mock_post.assert_not_called()

    def test_logs_what_would_have_been_sent(self, monkeypatch, caplog):
        import src.utils.email as email_module
        import src.utils.email_brevo as email_brevo_module
        monkeypatch.setattr(email_module, "is_prod", lambda: False)
        monkeypatch.setattr(email_brevo_module, "is_prod", lambda: False)

        with caplog.at_level("INFO"):
            asyncio.run(
                email_module.send_verification_email(
                    to="new@example.com",
                    name="Ada",
                    token="TOKEN123",
                    frontend_url="http://localhost:5173",
                )
            )

        assert "dev mode" in caplog.text
        assert "new@example.com" in caplog.text
        # The rendered HTML itself is not dumped into logs (multi-KB per line
        # is not useful) — the per-function link log below covers usability.
        assert "TOKEN123" in caplog.text  # from the redacted-link line, local host is exempt

    def test_dev_log_redacts_a_non_local_token(self, monkeypatch, caplog):
        """'Non-prod' includes staging, where the Axiom handler ships logs to a
        third party — so a link to a real hostname stays masked even in dev mode.
        Localhost links are exempt (see TestLocalLinksAreNotRedacted)."""
        import src.utils.email as email_module
        import src.utils.email_brevo as email_brevo_module
        monkeypatch.setattr(email_module, "is_prod", lambda: False)
        monkeypatch.setattr(email_brevo_module, "is_prod", lambda: False)

        with caplog.at_level("INFO"):
            asyncio.run(
                email_module.send_verification_email(
                    to="new@example.com",
                    name="Ada",
                    token="SUPERSECRET",
                    frontend_url="https://staging.cancer-bot.com",
                )
            )

        assert "SUPERSECRET" not in caplog.text
        assert "token=***" in caplog.text


class TestPasswordResetEmail:
    def test_send_password_reset_email_noop_when_no_api_key(self, as_prod, monkeypatch):
        monkeypatch.delenv("BREVO_API_KEY", raising=False)

        with patch("src.utils.email_brevo.requests.post") as mock_post:
            asyncio.run(as_prod.send_password_reset_email(
                "test@example.com", "Test User", "https://cancer-bot.com/reset?token=abc"))
            mock_post.assert_not_called()

    def test_send_password_reset_email_calls_brevo(self, as_prod, monkeypatch):
        monkeypatch.setenv("BREVO_API_KEY", "test-key-123")

        with patch("src.utils.email_brevo.requests.post") as mock_post:
            mock_post.return_value = _mock_post_response()

            assert asyncio.run(as_prod.send_password_reset_email(
                "user@example.com", "Alice", "https://cancer-bot.com/reset-password?token=tok123"
            )) is True

            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert args[0] == "https://api.brevo.com/v3/smtp/email"
            assert kwargs["headers"]["api-key"] == "test-key-123"

            body = kwargs["json"]
            assert body["to"] == [{"email": "user@example.com"}]
            assert body["subject"] == "Reset your CancerBot password 🔑"
            assert "Alice" in body["htmlContent"]
            assert "tok123" in body["htmlContent"]


class TestDeliveryFailureIsContained:
    """A send failure must never propagate as a raised exception. Callers
    enqueue these as arq jobs (src/jobs/email_jobs.py) run in the separate
    worker process, decoupled from the request that triggered them — a
    raised exception here wouldn't reach any client either way, but the
    contract (log and return False) matters regardless of where the call
    happens, so it's asserted directly rather than relied on implicitly."""

    def test_sender_returns_false_instead_of_raising(self, as_prod, monkeypatch, caplog):
        monkeypatch.setenv("BREVO_API_KEY", "test-key")

        with patch("src.utils.email_brevo.requests.post") as mock_post:
            mock_post.return_value = _mock_post_response(status=401)

            with caplog.at_level("ERROR"):
                result = asyncio.run(as_prod.send_password_reset_email(
                    "user@example.com", "User", "https://cancer-bot.com/reset-password?token=abc"
                ))

        assert result is False
        assert "delivery failed" in caplog.text
        assert "user@example.com" in caplog.text

    def test_every_sender_contains_its_failure(self, as_prod, monkeypatch):
        monkeypatch.setenv("BREVO_API_KEY", "test-key")

        with patch("src.utils.email_brevo.requests.post") as mock_post:
            mock_post.return_value = _mock_post_response(status=500)

            calls = [
                as_prod.send_verification_email(
                    to="a@b.c", name="N", token="t", frontend_url="http://x"),
                as_prod.send_account_deleted_email(to="a@b.c", name="N"),
                as_prod.send_password_reset_email(to="a@b.c", name="N", link="http://x?token=t"),
                as_prod.send_delete_account_request_email(
                    to="a@b.c", name="N", link="http://x?token=t"),
                as_prod.send_delete_account_scheduled_email(
                    to="a@b.c", name="N", deletion_date="January 1, 2027"),
                as_prod.send_delete_account_cancelled_email(to="a@b.c", name="N"),
                as_prod.send_fallback_alert("gpt-4o"),
            ]
            for coro in calls:
                assert asyncio.run(coro) is False

    def test_low_level_helper_still_raises(self, as_prod, monkeypatch):
        """_send_brevo keeps its strict contract — _deliver is the layer that
        decides a failure must not propagate."""
        monkeypatch.setenv("BREVO_API_KEY", "test-key")
        import src.utils.email_brevo as email_brevo_module

        with patch("src.utils.email_brevo.requests.post") as mock_post:
            mock_post.return_value = _mock_post_response(status=401)

            with pytest.raises(Exception, match="HTTP 401"):
                email_brevo_module._send_brevo("a@b.c", "subject", "<p>hi</p>")


class TestEveryPublicSenderRendersSuccessfully:
    """Each send_* wrapper must supply exactly the fields its template needs.

    str.format() is strict (unlike SendGrid's Handlebars, which silently
    rendered a missing {{{var}}} as empty) — a wrapper passing the wrong field
    set raises KeyError inside _render_template. That's exactly the kind of
    bug TestDeliveryFailureIsContained's `assert result is False` tests cannot
    catch: a KeyError is caught by _deliver's except right alongside a
    genuine simulated provider failure, and both come out as False. Asserting
    `is True` here on a real end-to-end call (only requests.post mocked)
    means a template/field mismatch fails this test distinctly instead of
    hiding behind that generic containment check. This caught a real bug:
    send_account_deleted_email originally omitted `link`, which the
    account_deleted template requires.
    """

    def test_every_sender_actually_delivers(self, as_prod, monkeypatch):
        monkeypatch.setenv("BREVO_API_KEY", "test-key")

        with patch("src.utils.email_brevo.requests.post") as mock_post:
            mock_post.return_value = _mock_post_response()

            calls = [
                as_prod.send_verification_email(
                    to="a@b.c", name="N", token="t", frontend_url="http://x"),
                as_prod.send_account_deleted_email(to="a@b.c", name="N"),
                as_prod.send_password_reset_email(to="a@b.c", name="N", link="http://x?token=t"),
                as_prod.send_delete_account_request_email(
                    to="a@b.c", name="N", link="http://x?token=t"),
                as_prod.send_delete_account_scheduled_email(
                    to="a@b.c", name="N", deletion_date="January 1, 2027"),
                as_prod.send_delete_account_cancelled_email(to="a@b.c", name="N"),
                as_prod.send_fallback_alert("gpt-4o"),
            ]
            for coro in calls:
                assert asyncio.run(coro) is True

            assert mock_post.call_count == len(calls)

    def test_fallback_alert_renders_model_name(self, as_prod, monkeypatch):
        monkeypatch.setenv("BREVO_API_KEY", "test-key")

        with patch("src.utils.email_brevo.requests.post") as mock_post:
            mock_post.return_value = _mock_post_response()
            assert asyncio.run(as_prod.send_fallback_alert("gpt-4o")) is True

        mock_post.assert_called_once()
        assert "gpt-4o" in mock_post.call_args.kwargs["json"]["htmlContent"]


class TestDormantSendgridPath:
    """_send_sendgrid/EMAIL_TEMPLATES are kept in email.py, unused by any live
    sender, in case SendGrid is ever reinstated. Minimal regression coverage
    only — the active path is Brevo, tested above."""

    def test_still_importable_and_callable(self, monkeypatch):
        sendgrid = pytest.importorskip("sendgrid", minversion="6.0")
        import src.utils.email as email_module
        monkeypatch.setattr(email_module, "is_prod", lambda: True)
        monkeypatch.setenv("SENDGRID_API_KEY", "test-key")

        with patch("sendgrid.SendGridAPIClient") as MockClient:
            mock_sg = MagicMock()
            MockClient.return_value = mock_sg

            email_module._send_sendgrid("a@b.c", "d-template", {"name": "N"})

            MockClient.assert_called_once_with("test-key")
            mock_sg.send.assert_called_once()
