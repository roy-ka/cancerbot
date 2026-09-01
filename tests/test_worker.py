import pytest

from src.worker import WorkerSettings, get_redis_settings, shutdown, startup


class TestGetRedisSettings:
    def test_parses_redis_url_with_password(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://:mypassword@redis-host:6380/2")
        settings = get_redis_settings()
        assert settings.host == "redis-host"
        assert settings.port == 6380
        assert settings.database == 2
        assert settings.password == "mypassword"

    def test_defaults_to_localhost_when_unset(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        settings = get_redis_settings()
        assert settings.host == "localhost"
        assert settings.port == 6379
        assert settings.database == 0


class TestWorkerSettings:
    def test_has_no_jobs_registered_yet(self):
        """Phase 1 is infrastructure only — jobs land in later phases."""
        assert WorkerSettings.functions == []
        assert WorkerSettings.cron_jobs == []

    def test_lifecycle_hooks_are_set(self):
        assert WorkerSettings.on_startup is startup
        assert WorkerSettings.on_shutdown is shutdown

    @pytest.mark.asyncio
    async def test_startup_and_shutdown_do_not_raise(self):
        await startup({})
        await shutdown({})

    def test_redis_settings_present(self):
        assert WorkerSettings.redis_settings is not None
