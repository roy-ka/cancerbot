"""Background worker: LLM-based cancer relevance classifier for user-provided URLs.

Poll loop:
  1. Claim one pending job with SELECT FOR UPDATE SKIP LOCKED
  2. Ask Ollama: is this content cancer-related? (yes/no)
  3. If yes → embed and index into OpenSearch sources_index
  4. Update job status to done/failed

Run:
    python -m src.workers.url_classifier
"""

import logging
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [url_classifier] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.getenv("URL_CLASSIFIER_POLL_INTERVAL", "10"))  # seconds

CLASSIFICATION_PROMPT = """You are a medical content classifier. Answer with exactly one word: yes or no.

Is the following content related to cancer research, cancer treatment, oncology, or cancer biology?

Content:
{text}

Answer (yes/no):"""


def _classify(content_text: str) -> tuple[bool, str]:
    """Call Ollama to classify content. Returns (is_cancer_related, raw_response)."""
    from src.classes.ollama_connector import OllamaConnector

    prompt = CLASSIFICATION_PROMPT.format(text=content_text[:3000])
    response = OllamaConnector.ollama.generate(
        model=OllamaConnector.gen_model,
        prompt=prompt,
        stream=False,
        options={"num_predict": 10, "temperature": 0},
    )
    raw = response.get("response", "").strip().lower()
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


def _process_one(db) -> bool:
    """Claim and process one pending job. Returns True if a job was found."""
    from sqlalchemy import text
    from src.db.models import UrlClassificationJob

    # Claim one job atomically — SKIP LOCKED prevents double-processing
    row = db.execute(
        text(
            "SELECT id FROM url_classification_jobs "
            "WHERE status = 'pending' "
            "ORDER BY created_at ASC "
            "LIMIT 1 "
            "FOR UPDATE SKIP LOCKED"
        )
    ).fetchone()

    if not row:
        return False

    job: UrlClassificationJob = db.get(UrlClassificationJob, row[0])
    job.status = "processing"
    db.commit()

    logger.info(f"[worker] Processing job {job.id} url={job.url}")

    try:
        cancer_related, reasoning = _classify(job.content_text)
        job.cancer_related = cancer_related
        job.llm_reasoning = reasoning
        logger.info(f"[worker] job={job.id} cancer_related={cancer_related} reasoning='{reasoning}'")

        if cancer_related:
            _index(job.url, job.content_text, job.title)

        job.status = "done"
    except Exception as e:
        logger.error(f"[worker] job={job.id} failed: {type(e).__name__}: {e}")
        job.status = "failed"
        job.error = f"{type(e).__name__}: {e}"

    job.processed_at = datetime.now(timezone.utc)
    db.commit()
    return True


STALE_PROCESSING_MINUTES = 15


def _reap_stale_jobs(db) -> None:
    """Reset jobs stuck in 'processing' for longer than STALE_PROCESSING_MINUTES."""
    from sqlalchemy import text
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
        logger.warning(f"[worker] Reaped {result.rowcount} stale processing job(s)")


def run() -> None:
    from src.db.session import SessionLocal

    logger.info(f"URL classifier worker started (poll_interval={POLL_INTERVAL}s)")

    while True:
        try:
            with SessionLocal() as db:
                _reap_stale_jobs(db)
                found = _process_one(db)
            if not found:
                time.sleep(POLL_INTERVAL)
        except Exception as e:
            logger.error(f"[worker] Unexpected error in poll loop: {type(e).__name__}: {e}")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
