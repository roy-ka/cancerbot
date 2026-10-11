"""arq jobs: LLM-based cancer-relevance classification for user-provided URLs.

Was a standalone polling worker (src/workers/url_classifier.py, `python -m
src.workers.url_classifier` in its own docker-compose service) that claimed
one pending row every POLL_INTERVAL seconds via SELECT FOR UPDATE SKIP
LOCKED. Now: conversation_helper.py's _enqueue_url_classification still
inserts the row (the table stays the audit/status record — status,
llm_reasoning, error, processed_at are all still genuinely useful to have
persisted), but immediately enqueues classify_url_job too, so classification
runs right away instead of waiting for the next poll tick.

reap_and_requeue_stale_url_classification_jobs is a cron job (see
src/worker.py) covering two failure modes an immediate-enqueue design still
needs a safety net for: a job stuck in 'processing' because its worker died
mid-job, and a job stuck in 'pending' because its insert-time enqueue call
failed (src.queue.enqueue never raises — a Redis blip there would otherwise
strand the job forever).
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CLASSIFICATION_PROMPT = """You are a medical content classifier. Answer with exactly one word: yes or no.

Is the following content related to cancer research, cancer treatment, oncology, or cancer biology?

Content:
{text}

Answer (yes/no):"""

STALE_PROCESSING_MINUTES = 15


async def _classify(content_text: str) -> tuple[bool, str]:
    """LLM-classify content via the shared provider chain (Ollama if
    configured, then Groq, then Gemini). Returns (is_cancer_related,
    raw_response). Raises if no provider answered, so the job is marked
    failed rather than silently recorded as "not cancer-related"."""
    from src.classes.ollama_connector import OllamaConnector

    prompt = CLASSIFICATION_PROMPT.format(text=content_text[:3000])
    # Not 10: the budget must leave room for a reasoning model's hidden
    # reasoning, or the one-word answer is never written at all.
    raw = await OllamaConnector.complete(prompt, max_tokens=200, label="url_classification")
    if raw is None:
        raise RuntimeError("no LLM provider returned a classification")
    raw = raw.strip().lower()
    return raw.startswith("yes"), raw


def _index(url: str, content_text: str, title: str | None) -> None:
    """Embed and index the URL content into OpenSearch."""
    from src.routers.conversation_helper import _embed_and_index_sources

    source = {
        "url": url,
        "title": title or url,
        "content_for_embedding": content_text,
        "source_type": "user_url",
        "tags": ["user_provided"],
    }
    indexed, skipped = _embed_and_index_sources([source])
    logger.info(f"[index] url={url} indexed={indexed} skipped={skipped}")


async def _process_claimed_job(db, job) -> None:
    """Classify an already-claimed job and index it if cancer-related.

    Split out from classify_url_job so this — the actual business logic —
    is testable against the ORM/SQLite test fixtures; classify_url_job's
    own FOR UPDATE SKIP LOCKED claim is Postgres-only syntax SQLite
    rejects outright, so it's tested separately with the DB layer mocked.
    """
    job.status = "processing"
    db.commit()

    logger.info(f"[url_classifier] processing job={job.id} url={job.url}")

    try:
        cancer_related, reasoning = await _classify(job.content_text)
        job.cancer_related = cancer_related
        job.llm_reasoning = reasoning
        logger.info(f"[url_classifier] job={job.id} cancer_related={cancer_related} reasoning='{reasoning}'")

        if cancer_related:
            await asyncio.to_thread(_index, job.url, job.content_text, job.title)

        job.status = "done"
    except Exception as e:
        logger.error(f"[url_classifier] job={job.id} failed: {type(e).__name__}: {e}")
        job.status = "failed"
        job.error = f"{type(e).__name__}: {e}"

    job.processed_at = datetime.now(timezone.utc)
    db.commit()


async def classify_url_job(ctx, *, job_id: str) -> None:
    """arq job — classify one URL-classification row and index it if
    cancer-related. Claims the row with FOR UPDATE SKIP LOCKED scoped to
    this specific id, so a duplicate enqueue of the same job_id (e.g. from
    both the insert-time call and a reaper re-enqueue racing it) can't
    double-process it.
    """
    from sqlalchemy import text
    from src.db.session import SessionLocal
    from src.db.models import UrlClassificationJob

    with SessionLocal() as db:
        row = db.execute(
            text(
                "SELECT id FROM url_classification_jobs "
                "WHERE id = :job_id AND status = 'pending' "
                "FOR UPDATE SKIP LOCKED"
            ),
            {"job_id": job_id},
        ).fetchone()

        if not row:
            logger.info("[url_classifier] job=%s not pending (already claimed or processed), skipping", job_id)
            return

        job: UrlClassificationJob = db.get(UrlClassificationJob, uuid.UUID(job_id))
        await _process_claimed_job(db, job)


async def reap_and_requeue_stale_url_classification_jobs(ctx) -> None:
    """Cron job — resets jobs stuck in 'processing' back to 'pending', then
    re-enqueues every pending job old enough that its own insert-time
    enqueue has had time to run (avoids racing a job inserted moments ago).
    """
    from sqlalchemy import text
    from src.db.session import SessionLocal
    from src.queue import enqueue

    with SessionLocal() as db:
        result = db.execute(
            text(
                "UPDATE url_classification_jobs SET status = 'pending', error = 'reaped: stuck in processing' "
                "WHERE status = 'processing' "
                "AND created_at < now() - :minutes * interval '1 minute'"
            ),
            {"minutes": STALE_PROCESSING_MINUTES},
        )
        db.commit()
        if result.rowcount:
            logger.warning(f"[url_classifier] reaped {result.rowcount} stale processing job(s)")

        rows = db.execute(
            text(
                "SELECT id FROM url_classification_jobs "
                "WHERE status = 'pending' AND created_at < now() - interval '1 minute'"
            )
        ).fetchall()

    for row in rows:
        await enqueue("classify_url_job", job_id=str(row[0]))
    if rows:
        logger.info(f"[url_classifier] re-enqueued {len(rows)} pending job(s)")
