import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routers import auth, health, conversations, bug_reports, terms, ninja, profile, shared
from src.retrieval.db_connector import dbConnector
from src.utils.utils import is_prod, ENV
import axiom_py
from axiom_py.logging import AxiomHandler
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

if not ENV:
    # is_prod() (src/utils/utils.py) treats a missing ENV as non-production —
    # several endpoints key off "not is_prod()" to return a live single-use
    # token (email verification, account deletion, email change) directly
    # in the API response, for E2E automation convenience.
    # A deployment that silently ends up on that branch because ENV was never
    # set is a token-disclosure bug, not a harmless default — refuse to boot
    # instead, mirroring the CORS_ORIGINS='*' refusal below.
    raise RuntimeError(
        "ENV is not set. Every deployment must set ENV explicitly "
        "(e.g. 'development', 'test', 'staging', 'production') — see example.env."
    )


class _HealthFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not ("/health" in msg and " 200" in msg)


if is_prod():
    logging.getLogger("uvicorn.access").addFilter(_HealthFilter())

def _init_axiom_logging() -> None:
    # Ingest-only token — see AXIOM_TOKEN_READ in src/jobs/admin_digest.py
    # for the separate, query-scoped token the daily digest queries with.
    token = os.getenv("AXIOM_TOKEN_WRITE")
    dataset = os.getenv("AXIOM_DATASET")
    if not token or not dataset:
        return
    client = axiom_py.Client(token=token)
    handler = AxiomHandler(client, dataset)
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    logger.info("Axiom logging initialized (dataset=%s)", dataset)

_init_axiom_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.nlp import load_models
    load_models()

    # Startup: Initialize OpenSearch indexes
    logger.info("Initializing OpenSearch indexes...")
    try:
        ok = dbConnector.ensure_all_indexes()
        if ok:
            logger.info("OpenSearch indexes initialized successfully")
        else:
            logger.warning("OpenSearch indexes could not be initialized — cluster may still be starting")
    except Exception as e:
        logger.warning(f"Failed to initialize OpenSearch indexes: {e}")

    # Account-deletion and auth-cleanup sweeps run as arq cron jobs in the
    # separate `worker` container (see src/worker.py) rather than as
    # in-process asyncio background tasks here.

    yield

    logger.info("Application shutting down")

app = FastAPI(lifespan=lifespan)

allow_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
allow_origins = [origin.strip() for origin in allow_origins]

# Starlette echoes the request Origin when credentials are allowed, so a
# wildcard here doesn't mean "public read-only API" — it means any site can
# make authenticated requests with the user's cookie and read the response.
if "*" in allow_origins:
    if is_prod():
        raise RuntimeError(
            "CORS_ORIGINS='*' cannot be combined with credentialed requests in production — "
            "it lets any origin issue authenticated requests with the user's session cookie. "
            "Set CORS_ORIGINS to an explicit comma-separated list of trusted origins."
        )
    logger.warning(
        "CORS_ORIGINS contains '*' with allow_credentials=True — every origin can make "
        "authenticated requests. Acceptable in development only; this refuses to start in production."
    )

# Every emailed link (verification, password reset, deletion, invites) is built
# from FRONTEND_URL; in production a missing value must not silently fall back
# to some default host.
if is_prod() and os.getenv("DEV_EMAIL_SHORTCUTS", "").strip().lower() in ("1", "true", "yes"):
    raise RuntimeError(
        "DEV_EMAIL_SHORTCUTS is set in production. It skips email verification and returns "
        "password-reset tokens in API responses — local development only."
    )

# Local development runs OpenSearch over plain HTTP (docker-compose.yml);
# production must use the TLS cluster from docker-compose.prod.yml.
if is_prod() and not os.getenv("OPENSEARCH_URL", "").strip().lower().startswith("https://"):
    raise RuntimeError(
        "OPENSEARCH_URL must be https:// in production. Plain-HTTP OpenSearch is for local "
        "development only — deploy with docker-compose.prod.yml (scripts/deploy.sh does)."
    )

if is_prod() and not os.getenv("FRONTEND_URL", "").strip():
    raise RuntimeError(
        "FRONTEND_URL is not set. Production must set it to the public frontend origin "
        "(e.g. https://example.com) — it's used to build every link in outgoing email."
    )

app.add_middleware(
  CORSMiddleware,
  allow_origins=allow_origins,
  allow_credentials=True,
  allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
  allow_headers=["Content-Type", "Authorization"],
)

app.include_router(auth.router)
app.include_router(health.router)
app.include_router(conversations.router)
app.include_router(bug_reports.router)
app.include_router(terms.router)
app.include_router(ninja.router)
app.include_router(profile.router)
app.include_router(shared.router)
