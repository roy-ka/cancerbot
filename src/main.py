import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routers import auth, health, conversations, bug_reports, terms
from src.retrieval.db_connector import dbConnector
from src.utils.utils import is_prod
import axiom_py
from axiom_py.logging import AxiomHandler
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


class _HealthFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not ("/health" in msg and " 200" in msg)


if is_prod():
    logging.getLogger("uvicorn.access").addFilter(_HealthFilter())

def _init_axiom_logging() -> None:
    token = os.getenv("AXIOM_TOKEN")
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
app.include_router(terms.router)
