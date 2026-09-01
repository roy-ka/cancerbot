import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db import models
from src.jobs.url_classification import (
    _process_claimed_job,
    classify_url_job,
    reap_and_requeue_stale_url_classification_jobs,
)
from src.routers.conversation_helper import _enqueue_url_classification


def _make_job(db_session, status="pending"):
    job = models.UrlClassificationJob(
        url="https://example.com/article",
        content_text="Some article content about oncology.",
        title="An Article",
        status=status,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


class TestProcessClaimedJob:
    """The actual classify/index/error-handling logic — tested against the
    real ORM fixtures since it takes an already-loaded job and does no raw
    SQL itself (unlike classify_url_job's FOR UPDATE SKIP LOCKED claim)."""

    @pytest.mark.asyncio
    async def test_cancer_related_job_gets_indexed_and_marked_done(self, db_session):
        job = _make_job(db_session)

        with patch("src.jobs.url_classification._classify", return_value=(True, "yes")) as mock_classify, \
             patch("src.jobs.url_classification._index") as mock_index:
            await _process_claimed_job(db_session, job)

        mock_classify.assert_called_once_with(job.content_text)
        mock_index.assert_called_once_with(job.url, job.content_text, job.title)
        assert job.status == "done"
        assert job.cancer_related is True
        assert job.llm_reasoning == "yes"
        assert job.processed_at is not None

    @pytest.mark.asyncio
    async def test_non_cancer_related_job_is_not_indexed(self, db_session):
        job = _make_job(db_session)

        with patch("src.jobs.url_classification._classify", return_value=(False, "no")), \
             patch("src.jobs.url_classification._index") as mock_index:
            await _process_claimed_job(db_session, job)

        mock_index.assert_not_called()
        assert job.status == "done"
        assert job.cancer_related is False

    @pytest.mark.asyncio
    async def test_classify_error_marks_job_failed(self, db_session):
        job = _make_job(db_session)

        with patch("src.jobs.url_classification._classify", side_effect=RuntimeError("groq down")), \
             patch("src.jobs.url_classification._index") as mock_index:
            await _process_claimed_job(db_session, job)

        mock_index.assert_not_called()
        assert job.status == "failed"
        assert "groq down" in job.error
        assert job.processed_at is not None

    @pytest.mark.asyncio
    async def test_index_error_marks_job_failed(self, db_session):
        job = _make_job(db_session)

        with patch("src.jobs.url_classification._classify", return_value=(True, "yes")), \
             patch("src.jobs.url_classification._index", side_effect=RuntimeError("opensearch down")):
            await _process_claimed_job(db_session, job)

        assert job.status == "failed"
        assert "opensearch down" in job.error

    @pytest.mark.asyncio
    async def test_job_marked_processing_before_classification_starts(self, db_session):
        """Guards against the whole point of the status column silently
        regressing — processing must be visible/committed before the
        (slow) classify call, not just set in memory at the end."""
        job = _make_job(db_session)
        seen_status = {}

        def _capture_status(content_text):
            seen_status["status"] = job.status
            return (True, "yes")

        with patch("src.jobs.url_classification._classify", side_effect=_capture_status), \
             patch("src.jobs.url_classification._index"):
            await _process_claimed_job(db_session, job)

        assert seen_status["status"] == "processing"


class TestClassifyUrlJob:
    """classify_url_job's own claim step uses FOR UPDATE SKIP LOCKED, which
    is Postgres-only syntax SQLite rejects — tested here with the DB layer
    mocked rather than against the real (SQLite) test fixtures."""

    @pytest.mark.asyncio
    async def test_skips_when_row_not_pending(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = None
        mock_session_cm = MagicMock()
        mock_session_cm.__enter__.return_value = mock_db
        mock_session_cm.__exit__.return_value = False

        with patch("src.db.session.SessionLocal", return_value=mock_session_cm), \
             patch("src.jobs.url_classification._process_claimed_job", new_callable=AsyncMock) as mock_process:
            await classify_url_job({}, job_id="00000000-0000-0000-0000-000000000000")

        mock_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_processes_when_row_is_pending(self):
        job_id = "11111111-1111-1111-1111-111111111111"
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = (job_id,)
        fake_job = MagicMock()
        mock_db.get.return_value = fake_job
        mock_session_cm = MagicMock()
        mock_session_cm.__enter__.return_value = mock_db
        mock_session_cm.__exit__.return_value = False

        with patch("src.db.session.SessionLocal", return_value=mock_session_cm), \
             patch("src.jobs.url_classification._process_claimed_job", new_callable=AsyncMock) as mock_process:
            await classify_url_job({}, job_id=job_id)

        mock_process.assert_called_once_with(mock_db, fake_job)


class TestEnqueueUrlClassification:
    """_enqueue_url_classification (conversation_helper.py) is the insert
    side — it stays the audit/status record and now also has to return the
    new row's id so the caller can enqueue classify_url_job for it."""

    def test_inserts_row_and_returns_its_id(self, db_session, TestingSessionLocal):
        with patch("src.db.session.SessionLocal", TestingSessionLocal):
            job_id = _enqueue_url_classification(
                url="https://example.com/a", content_text="content", title="Title"
            )

        assert job_id is not None
        db_session.expire_all()
        job = db_session.query(models.UrlClassificationJob).filter(
            models.UrlClassificationJob.id == uuid.UUID(job_id)
        ).first()
        assert job is not None
        assert job.url == "https://example.com/a"
        assert job.status == "pending"

    def test_returns_none_on_db_error(self, TestingSessionLocal):
        broken_session_factory = MagicMock(side_effect=RuntimeError("db down"))
        with patch("src.db.session.SessionLocal", broken_session_factory):
            job_id = _enqueue_url_classification(url="https://example.com/b", content_text="c", title=None)

        assert job_id is None


class TestReapAndRequeue:
    @pytest.mark.asyncio
    async def test_reenqueues_every_stale_pending_row(self):
        mock_db = MagicMock()
        update_result = MagicMock(rowcount=1)
        mock_db.execute.side_effect = [
            update_result,
            MagicMock(fetchall=lambda: [("job-a",), ("job-b",)]),
        ]
        mock_session_cm = MagicMock()
        mock_session_cm.__enter__.return_value = mock_db
        mock_session_cm.__exit__.return_value = False

        with patch("src.db.session.SessionLocal", return_value=mock_session_cm), \
             patch("src.queue.enqueue", new_callable=AsyncMock) as mock_enqueue:
            await reap_and_requeue_stale_url_classification_jobs({})

        assert mock_enqueue.call_count == 2
        mock_enqueue.assert_any_call("classify_url_job", job_id="job-a")
        mock_enqueue.assert_any_call("classify_url_job", job_id="job-b")

    @pytest.mark.asyncio
    async def test_noop_when_nothing_stale_or_pending(self):
        mock_db = MagicMock()
        mock_db.execute.side_effect = [
            MagicMock(rowcount=0),
            MagicMock(fetchall=lambda: []),
        ]
        mock_session_cm = MagicMock()
        mock_session_cm.__enter__.return_value = mock_db
        mock_session_cm.__exit__.return_value = False

        with patch("src.db.session.SessionLocal", return_value=mock_session_cm), \
             patch("src.queue.enqueue", new_callable=AsyncMock) as mock_enqueue:
            await reap_and_requeue_stale_url_classification_jobs({})

        mock_enqueue.assert_not_called()
