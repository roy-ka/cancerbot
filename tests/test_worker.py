import pytest
from unittest.mock import patch, AsyncMock

from src.jobs.account_deletion import delete_scheduled_user_job
from src.jobs.auth_cleanup import auth_cleanup_sweep
from src.jobs.email_jobs import (
    send_verification_email_job,
    send_password_reset_email_job,
    send_delete_account_request_email_job,
    send_delete_account_scheduled_email_job,
    send_delete_account_cancelled_email_job,
    send_fallback_alert_job,
    send_waitlist_joined_email_job,
    send_waitlist_invited_email_job,
    send_email_change_request_email_job,
    send_email_change_verification_email_job,
    send_email_changed_notice_email_job,
)
from src.jobs.url_classification import (
    classify_url_job,
    reap_and_requeue_stale_url_classification_jobs,
)
from src.jobs.admin_digest import daily_admin_digest, weekly_admin_digest
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
            send_waitlist_invited_email_job,
            send_email_change_request_email_job,
            send_email_change_verification_email_job,
            send_email_changed_notice_email_job,
            classify_url_job,
            delete_scheduled_user_job,
        }

    def test_all_cron_jobs_registered(self):
        cron_coroutines = {job.coroutine for job in WorkerSettings.cron_jobs}
        assert cron_coroutines == {
            auth_cleanup_sweep,
            reap_and_requeue_stale_url_classification_jobs,
            daily_admin_digest,
            weekly_admin_digest,
        }

    def test_url_classification_reaper_runs_every_five_minutes(self):
        job = next(
            j for j in WorkerSettings.cron_jobs
            if j.coroutine is reap_and_requeue_stale_url_classification_jobs
        )
        assert job.minute == set(range(0, 60, 5))

    def test_auth_cleanup_sweep_runs_every_six_hours_at_startup(self):
        job = next(j for j in WorkerSettings.cron_jobs if j.coroutine is auth_cleanup_sweep)
        assert job.hour == {0, 6, 12, 18}
        assert job.minute == 0
        assert job.run_at_startup is True

    def test_daily_admin_digest_runs_at_0100_utc(self):
        job = next(j for j in WorkerSettings.cron_jobs if j.coroutine is daily_admin_digest)
        assert job.hour == 1
        assert job.minute == 0

    def test_weekly_admin_digest_runs_sunday_0200_utc(self):
        job = next(j for j in WorkerSettings.cron_jobs if j.coroutine is weekly_admin_digest)
        assert job.weekday == 'sun'
        assert job.hour == 2
        assert job.minute == 0

    def test_lifecycle_hooks_are_set(self):
        assert WorkerSettings.on_startup is startup
        assert WorkerSettings.on_shutdown is shutdown

    @pytest.mark.asyncio
    async def test_startup_and_shutdown_do_not_raise(self):
        # reschedule_pending_deletions opens its own real SessionLocal and
        # would otherwise hit whatever DB this test process is configured
        # against — it has its own dedicated coverage in
        # tests/test_account_deletion_job.py, so it's mocked out here.
        with patch("src.worker.reschedule_pending_deletions", new=AsyncMock()):
            await startup({})
        await shutdown({})

    @pytest.mark.asyncio
    async def test_startup_calls_reschedule_pending_deletions(self):
        with patch("src.worker.reschedule_pending_deletions", new=AsyncMock()) as mock_reschedule:
            await startup({})
        mock_reschedule.assert_awaited_once()

    def test_redis_settings_present(self):
        assert WorkerSettings.redis_settings is not None
