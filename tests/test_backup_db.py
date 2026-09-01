from pathlib import Path
from unittest.mock import Mock, patch

from scripts.backup_db import backup_to_drive, get_postgres_url


class TestGetPostgresUrl:
    """Regression coverage for the incident where daily_backup.sh's bash
    `source .env` shell-interpreted an unquoted `&` in POSTGRES_PASSWORD,
    corrupting POSTGRES_URL before Python ever saw it (fixed by loading
    .env via python-dotenv instead of bash sourcing). This doesn't test
    the shell script, but locks in that get_postgres_url() itself parses a
    password containing shell-special characters correctly once the value
    actually reaches Python intact.
    """

    def test_parses_password_with_shell_special_characters(self, monkeypatch):
        monkeypatch.setenv(
            "POSTGRES_URL",
            "postgresql+asyncpg://cancerbot:Dmy&z33CJP@localhost:5432/cancerbot",
        )
        db = get_postgres_url()
        assert db["user"] == "cancerbot"
        assert db["password"] == "Dmy&z33CJP"
        assert db["host"] == "localhost"
        assert db["port"] == 5432
        assert db["db"] == "cancerbot"

    def test_raises_when_unset(self, monkeypatch):
        monkeypatch.delenv("POSTGRES_URL", raising=False)
        try:
            get_postgres_url()
            assert False, "expected ValueError"
        except ValueError as e:
            assert "POSTGRES_URL not set" in str(e)

    def test_unparseable_port_reports_structure_without_leaking_password(self, monkeypatch):
        # A malformed URL (password containing an unencoded '/', which is not
        # safely embeddable per RFC 3986) truncates netloc before the real
        # host:port — reproduces the "Port could not be cast" failure with a
        # made-up secret, to confirm the diagnostic never echoes it back.
        monkeypatch.setenv(
            "POSTGRES_URL",
            "postgresql+asyncpg://cancerbot:TotallyFakeSecret/xyz@localhost:5432/cancerbot",
        )
        try:
            get_postgres_url()
            assert False, "expected ValueError"
        except ValueError as e:
            msg = str(e)
            assert "TotallyFakeSecret" not in msg
            assert "url_len=" in msg
            assert "netloc_len=" in msg
            assert "at_count=" in msg


class TestBackupToDrive:
    def test_exits_when_not_configured(self, monkeypatch, capsys):
        monkeypatch.delenv("GOOGLE_OAUTH_TOKEN_FILE", raising=False)
        monkeypatch.delenv("GOOGLE_DRIVE_BACKUP_FOLDER_ID", raising=False)

        try:
            backup_to_drive(Path("dummy.dump"))
            assert False, "expected SystemExit"
        except SystemExit as e:
            assert e.code == 1
        assert "not set" in capsys.readouterr().out

    def test_uploads_with_configured_env(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_FILE", "/fake/sa.json")
        monkeypatch.setenv("GOOGLE_DRIVE_BACKUP_FOLDER_ID", "folder-abc")

        mock_upload = Mock(return_value="file-id-123")
        with patch("scripts.backup_drive.upload_to_drive", mock_upload):
            backup_to_drive(Path("dummy.dump"))

        mock_upload.assert_called_once_with(Path("dummy.dump"), "folder-abc", "/fake/sa.json")
