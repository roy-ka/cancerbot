import pytest
import asyncio
from unittest.mock import patch, MagicMock

sendgrid = pytest.importorskip("sendgrid", minversion="6.0")


class TestPasswordResetEmail:
    def test_send_password_reset_email_noop_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)

        with patch("sendgrid.SendGridAPIClient") as mock_client:
            from src.utils.email import send_password_reset_email
            asyncio.run(send_password_reset_email("test@example.com", "Test User", "https://cancer-bot.com/reset?token=abc"))
            mock_client.assert_not_called()

    def test_send_password_reset_email_calls_sendgrid(self, monkeypatch):
        monkeypatch.setenv("SENDGRID_API_KEY", "test-key-123")
        monkeypatch.setenv("EMAIL_FROM", "noreply@test.com")
        monkeypatch.setenv("EMAIL_FROM_NAME", "TestBot")

        with patch("sendgrid.SendGridAPIClient") as MockClient:
            mock_sg = MagicMock()
            MockClient.return_value = mock_sg

            from src.utils.email import send_password_reset_email
            asyncio.run(send_password_reset_email(
                "user@example.com", "Alice", "https://cancer-bot.com/reset-password?token=tok123"
            ))

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

    def test_send_password_reset_email_raises_on_sendgrid_error(self, monkeypatch):
        monkeypatch.setenv("SENDGRID_API_KEY", "test-key")
        monkeypatch.setenv("EMAIL_FROM", "noreply@test.com")

        with patch("sendgrid.SendGridAPIClient") as MockClient:
            mock_sg = MagicMock()
            mock_sg.send.side_effect = Exception("SendGrid API error")
            MockClient.return_value = mock_sg

            from src.utils.email import send_password_reset_email
            with pytest.raises(Exception, match="SendGrid API error"):
                asyncio.run(send_password_reset_email(
                    "user@example.com", "User", "https://cancer-bot.com/reset-password?token=abc"
                ))
