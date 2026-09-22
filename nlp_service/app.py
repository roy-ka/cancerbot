import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from starlette.concurrency import run_in_threadpool
import axiom_py
from axiom_py.logging import AxiomHandler

load_dotenv()

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class _HealthFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not ("/health" in msg and " 200" in msg)


if os.getenv("ENV", "").lower() in ("prod", "production"):
    logging.getLogger("uvicorn.access").addFilter(_HealthFilter())


def _init_axiom_logging() -> None:
    # Ingest-only token — see AXIOM_TOKEN_READ in src/jobs/admin_digest.py
    # (backend service) for the separate, query-scoped token.
    token = os.getenv("AXIOM_TOKEN_WRITE")
    dataset = os.getenv("AXIOM_DATASET")
    if not token or not dataset:
        return
    client = axiom_py.Client(token=token)
    handler = AxiomHandler(client, dataset)
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    logger.info("[NLP] Axiom logging initialized (dataset=%s)", dataset)


_init_axiom_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("[lifespan] Startup complete")
    yield
    logger.info("[lifespan] Shutdown")


app = FastAPI(title="Cancerbot NLP Service", lifespan=lifespan)

# Model loading (spaCy/scispaCy) and the extraction/spelling logic itself
# live in extraction.py — split out so tests can import just that, without
# also paying for the CrossEncoder load below (torch + sentence-transformers,
# unrelated to extraction/spelling).
from extraction import extract_entities, correct_spelling_text

logger.info("[startup] Loading cross-encoder 'cross-encoder/ms-marco-MiniLM-L-6-v2'...")
from sentence_transformers import CrossEncoder

reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
logger.info("[startup] Cross-encoder ready")


# Upper bound on text accepted by the pipeline endpoints. A scispaCy parse is
# CPU-bound and roughly linear in input size, and this service has no auth of
# its own, so an unbounded `text` field is a cheap denial-of-service: one large
# body ties up a worker for seconds. Comfortably above any real chat message
# (the API caps those at 4000 chars) and above a scraped page excerpt.
# NOTE: this bounds the *parsed* text, not the raw request body — put a body
# size limit on the reverse proxy in front of this service as well.
MAX_TEXT_CHARS = 20_000


class ExtractReq(BaseModel):
    text: str = Field(..., max_length=MAX_TEXT_CHARS)


class SpellingReq(BaseModel):
    text: str = Field(..., max_length=MAX_TEXT_CHARS)


# Reranking operates on already-retrieved, already-gated chunks (MAX_RESULTS
# in src/retrieval/search.py, currently 10) — these bounds exist for the same
# no-auth DoS reason as MAX_TEXT_CHARS, sized to that caller rather than to
# an arbitrary worst case.
MAX_RERANK_DOCS = 32
MAX_RERANK_DOC_CHARS = 2_000


class RerankReq(BaseModel):
    query: str = Field(..., max_length=MAX_TEXT_CHARS)
    documents: list[str] = Field(..., max_length=MAX_RERANK_DOCS)


@app.post("/extract")
async def extract(req: ExtractReq):
    t0 = time.time()
    logger.info("[extract] input: %r", (req.text or "")[:200])
    result = await run_in_threadpool(extract_entities, req.text or "")
    logger.info(
        "[extract] %.3fs — entities=%s abbr=%s expanded=%s synonyms=%s",
        time.time() - t0,
        result["entities"],
        result["abbreviations_found"],
        result["expanded_entities"],
        result["synonyms"],
    )
    return result


@app.post("/spelling/correct")
async def spelling_correct(req: SpellingReq):
    t0 = time.time()
    result = await run_in_threadpool(correct_spelling_text, req.text or "")
    logger.info("[spelling] %.3fs — %d changes", time.time() - t0, len(result["changes"]))
    return result


@app.post("/rerank")
async def rerank(req: RerankReq):
    t0 = time.time()
    if not req.documents:
        return {"scores": []}

    documents = [d[:MAX_RERANK_DOC_CHARS] for d in req.documents]
    pairs = [(req.query, doc) for doc in documents]
    scores = await run_in_threadpool(reranker.predict, pairs)
    logger.info("[rerank] %.3fs — %d documents", time.time() - t0, len(documents))
    return {"scores": [float(s) for s in scores]}


@app.get("/health")
def health():
    return {"ok": True}
