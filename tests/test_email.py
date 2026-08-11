import pytest
import asyncio
from unittest.mock import patch, MagicMock

sendgrid = pytest.importorskip("sendgrid", minversion="6.0")


@pytest.fixture
def as_prod(monkeypatch):
    """Force the production branch.

    Outside production `_send_sendgrid` deliberately short-circuits and never
    touches SendGrid, so any test that wants to exercise real delivery has to
    opt in. `ENV` is read once at import in src.utils.utils, so patching the
    is_prod reference email.py holds is the reliable way to flip this.
    """
    import src.utils.email as email_module
    monkeypatch.setattr(email_module, "is_prod", lambda: True)
    return email_module


class TestDevModeDoesNotSend:
    def test_no_sendgrid_call_outside_production(self, monkeypatch):
        import src.utils.email as email_module
        monkeypatch.setattr(email_module, "is_prod", lambda: False)
        monkeypatch.setenv("SENDGRID_API_KEY", "looks-real-but-unused")

        with patch("sendgrid.SendGridAPIClient") as mock_client:
            assert asyncio.run(
                email_module.send_password_reset_email(
                    "user@example.com", "User", "https://app/reset-password?token=abc"
                )
            ) is True
            mock_client.assert_not_called()

    def test_logs_what_would_have_been_sent(self, monkeypatch, caplog):
        import src.utils.email as email_module
        monkeypatch.setattr(email_module, "is_prod", lambda: False)

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
        assert "Ada" in caplog.text  # the payload itself is visible

    def test_dev_log_redacts_a_non_local_token(self, monkeypatch, caplog):
        """'Non-prod' includes staging, where the Axiom handler ships logs to a
        third party — so a link to a real hostname stays masked even in dev mode.
        Localhost links are exempt (see TestLocalLinksAreNotRedacted)."""
        import src.utils.email as email_module
        monkeypatch.setattr(email_module, "is_prod", lambda: False)

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
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)

        with patch("sendgrid.SendGridAPIClient") as mock_client:
            asyncio.run(as_prod.send_password_reset_email(
                "test@example.com", "Test User", "https://cancer-bot.com/reset?token=abc"))
            mock_client.assert_not_called()

    def test_send_password_reset_email_calls_sendgrid(self, as_prod, monkeypatch):
        monkeypatch.setenv("SENDGRID_API_KEY", "test-key-123")
        monkeypatch.setenv("EMAIL_FROM", "noreply@test.com")
        monkeypatch.setenv("EMAIL_FROM_NAME", "TestBot")

        with patch("sendgrid.SendGridAPIClient") as MockClient:
            mock_sg = MagicMock()
            MockClient.return_value = mock_sg

            assert asyncio.run(as_prod.send_password_reset_email(
                "user@example.com", "Alice", "https://cancer-bot.com/reset-password?token=tok123"
            )) is True

            MockClient.assert_called_once_with("test-key-123")
            mock_sg.send.assert_called_once()

            # Verify the mail object targets the right template and dynamic data
            call_args = mock_sg.send.call_args
            mail_obj = call_args[0][0]
            mail_dict = mail_obj.get()
            assert mail_dict.get("template_id") == "d-89a37afdde454f699046dda66cfca385"
            dynamic_data = mail_dict["personalizations"][0].get("dynamic_template_data", {})
            assert dynamic_data["name"] == "Alice"
            assert "tok123" in dynamic_data["link"]


class TestDeliveryFailureIsContained:
    """A send failure must not escape into the ASGI layer. Every caller registers
    these as FastAPI BackgroundTasks, which run after the response is already
    sent — so a raised exception can't reach the client and only shows up as an
    unhandled traceback for something already logged."""

    def test_sender_returns_false_instead_of_raising(self, as_prod, monkeypatch, caplog):
        monkeypatch.setenv("SENDGRID_API_KEY", "test-key")

        with patch("sendgrid.SendGridAPIClient") as MockClient:
            mock_sg = MagicMock()
            mock_sg.send.side_effect = Exception("SendGrid API error")
            MockClient.return_value = mock_sg

            with caplog.at_level("ERROR"):
                result = asyncio.run(as_prod.send_password_reset_email(
                    "user@example.com", "User", "https://cancer-bot.com/reset-password?token=abc"
                ))

        assert result is False
        assert "delivery failed" in caplog.text
        assert "user@example.com" in caplog.text

    def test_every_sender_contains_its_failure(self, as_prod, monkeypatch):
        monkeypatch.setenv("SENDGRID_API_KEY", "test-key")

        with patch("sendgrid.SendGridAPIClient") as MockClient:
            mock_sg = MagicMock()
            mock_sg.send.side_effect = Exception("boom")
            MockClient.return_value = mock_sg

            calls = [
                as_prod.send_verification_email(
                    to="a@b.c", name="N", token="t", frontend_url="http://x"),
                as_prod.send_account_deleted_email(to="a@b.c", name="N"),
                as_prod.send_password_reset_email(to="a@b.c", name="N", link="http://x?token=t"),
                as_prod.send_delete_account_request_email(
                    to="a@b.c", name="N", link="http://x?token=t"),
                as_prod.send_delete_account_scheduled_email(
                    to="a@b.c", name="N", deletion_date="January 1, 2027"),
            ]
            for coro in calls:
                assert asyncio.run(coro) is False

    def test_low_level_helper_still_raises(self, as_prod, monkeypatch):
        """_send_sendgrid keeps its strict contract — _deliver is the layer that
        decides a failure must not propagate."""
        monkeypatch.setenv("SENDGRID_API_KEY", "test-key")

        with patch("sendgrid.SendGridAPIClient") as MockClient:
            mock_sg = MagicMock()
            mock_sg.send.side_effect = Exception("SendGrid API error")
            MockClient.return_value = mock_sg

            with pytest.raises(Exception, match="SendGrid API error"):
                as_prod._send_sendgrid("a@b.c", "d-template", {"name": "N"})
