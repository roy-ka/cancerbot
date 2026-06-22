import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routers import auth, health, conversations, bug_reports
from src.retrieval.db_connector import dbConnector
from src.utils.utils import is_prod
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

def _init_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
        sentry_sdk.init(
            dsn=dsn,
            # FastAPI, Starlette, SQLAlchemy auto-discovered when installed
            integrations=[
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            environment="production" if is_prod() else "development",
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
        logger.info("Sentry initialized (env=%s)", "production" if is_prod() else "development")
    except Exception as exc:
        logger.warning("Failed to initialize Sentry: %s", exc)

_init_sentry()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load NLP models — fail fast if en_core_sci_sm is not installed
    from src.nlp import load_models
    await asyncio.to_thread(load_models)

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

    yield

    # Shutdown: Cleanup if needed
    logger.info("Application shutting down")

app = FastAPI(lifespan=lifespan)

allow_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
allow_origins = [origin.strip() for origin in allow_origins]

app.add_middleware(
  CORSMiddleware,
  allow_origins=allow_origins,
  allow_credentials=True,
  allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
  allow_headers=["Content-Type", "Authorization"],
)

app.include_router(auth.router)
app.include_router(health.router)
app.include_router(conversations.router)
app.include_router(bug_reports.router)
