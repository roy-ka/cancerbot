import pytest
import asyncio
from unittest.mock import patch, MagicMock

sendgrid = pytest.importorskip("sendgrid", minversion="6.0")


class TestPasswordResetEmail:
    def test_send_password_reset_email_noop_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)

        with patch("sendgrid.SendGridAPIClient") as mock_client:
            from src.utils.email import send_password_reset_email
            asyncio.run(send_password_reset_email("test@example.com", "123456"))
            mock_client.assert_not_called()

    def test_send_password_reset_email_calls_sendgrid(self, monkeypatch):
        monkeypatch.setenv("SENDGRID_API_KEY", "test-key-123")
        monkeypatch.setenv("EMAIL_FROM", "noreply@test.com")
        monkeypatch.setenv("EMAIL_FROM_NAME", "TestBot")

        with patch("sendgrid.SendGridAPIClient") as MockClient:
            mock_sg = MagicMock()
            MockClient.return_value = mock_sg

            from src.utils.email import send_password_reset_email
            asyncio.run(send_password_reset_email("user@example.com", "654321"))

            MockClient.assert_called_once_with("test-key-123")
            mock_sg.send.assert_called_once()

            # Verify the mail object was constructed correctly
            call_args = mock_sg.send.call_args
            mail_obj = call_args[0][0]
            assert str(mail_obj.from_email.email) == "noreply@test.com"
            assert "654321" in mail_obj.html_content

    def test_send_password_reset_email_raises_on_sendgrid_error(self, monkeypatch):
        monkeypatch.setenv("SENDGRID_API_KEY", "test-key")
        monkeypatch.setenv("EMAIL_FROM", "noreply@test.com")

        with patch("sendgrid.SendGridAPIClient") as MockClient:
            mock_sg = MagicMock()
            mock_sg.send.side_effect = Exception("SendGrid API error")
            MockClient.return_value = mock_sg

            from src.utils.email import send_password_reset_email
            with pytest.raises(Exception, match="SendGrid API error"):
                asyncio.run(send_password_reset_email("user@example.com", "123456"))

    def test_send_password_reset_email_html_contains_code(self, monkeypatch):
        monkeypatch.setenv("SENDGRID_API_KEY", "test-key")
        monkeypatch.setenv("EMAIL_FROM", "noreply@test.com")

        with patch("sendgrid.SendGridAPIClient") as MockClient:
            mock_sg = MagicMock()
            MockClient.return_value = mock_sg

            from src.utils.email import send_password_reset_email
            asyncio.run(send_password_reset_email("user@example.com", "999888"))

            call_args = mock_sg.send.call_args
            mail_obj = call_args[0][0]
            assert "999888" in mail_obj.html_content
            assert "reset" in mail_obj.html_content.lower()
            assert mail_obj.subject == "Your CancerBot password reset code"
