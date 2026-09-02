import pytest

from src.jobs.account_deletion import account_deletion_sweep
from src.jobs.auth_cleanup import auth_cleanup_sweep
from src.jobs.email_jobs import (
    send_verification_email_job,
    send_password_reset_email_job,
    send_delete_account_request_email_job,
    send_delete_account_scheduled_email_job,
    send_delete_account_cancelled_email_job,
    send_fallback_alert_job,
    send_waitlist_joined_email_job,
)
from src.jobs.url_classification import (
    classify_url_job,
    reap_and_requeue_stale_url_classification_jobs,
)
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
    def test_all_on_demand_jobs_registered(self):
        assert set(WorkerSettings.functions) == {
            send_verification_email_job,
            send_password_reset_email_job,
            send_delete_account_request_email_job,
            send_delete_account_scheduled_email_job,
            send_delete_account_cancelled_email_job,
            send_fallback_alert_job,
            send_waitlist_joined_email_job,
            classify_url_job,
        }

    def test_all_cron_jobs_registered(self):
        cron_coroutines = {job.coroutine for job in WorkerSettings.cron_jobs}
        assert cron_coroutines == {
            account_deletion_sweep,
            auth_cleanup_sweep,
            reap_and_requeue_stale_url_classification_jobs,
        }

    def test_url_classification_reaper_runs_every_five_minutes(self):
        job = next(
            j for j in WorkerSettings.cron_jobs
            if j.coroutine is reap_and_requeue_stale_url_classification_jobs
        )
        assert job.minute == set(range(0, 60, 5))

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
