import pytest

from src.jobs.account_deletion import account_deletion_sweep
from src.jobs.auth_cleanup import auth_cleanup_sweep
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
    def test_no_ad_hoc_jobs_registered_yet(self):
        """Phase 2 only adds cron jobs — enqueue-on-demand jobs (email,
        url_classifier) land in later phases."""
        assert WorkerSettings.functions == []

    def test_sweep_cron_jobs_registered(self):
        cron_coroutines = {job.coroutine for job in WorkerSettings.cron_jobs}
        assert cron_coroutines == {account_deletion_sweep, auth_cleanup_sweep}

    def test_account_deletion_sweep_runs_hourly_at_startup(self):
        job = next(j for j in WorkerSettings.cron_jobs if j.coroutine is account_deletion_sweep)
        assert job.hour is None  # every hour
        assert job.minute == 0
        assert job.run_at_startup is True

    def test_auth_cleanup_sweep_runs_every_six_hours_at_startup(self):
        job = next(j for j in WorkerSettings.cron_jobs if j.coroutine is auth_cleanup_sweep)
        assert job.hour == {0, 6, 12, 18}
        assert job.minute == 0
        assert job.run_at_startup is True

    def test_lifecycle_hooks_are_set(self):
        assert WorkerSettings.on_startup is startup
        assert WorkerSettings.on_shutdown is shutdown

    @pytest.mark.asyncio
    async def test_startup_and_shutdown_do_not_raise(self):
        await startup({})
        await shutdown({})

    def test_redis_settings_present(self):
        assert WorkerSettings.redis_settings is not None
