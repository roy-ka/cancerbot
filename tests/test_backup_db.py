from scripts.backup_db import get_postgres_url


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
