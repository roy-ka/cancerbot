import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routers import auth, health, conversations, bug_reports, terms, ninja
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

def _ensure_ninja_user() -> None:
    """Create the privileged ninja account from env vars if it doesn't exist yet.

    Idempotent — safe to call on every startup. No-op if NINJA_EMAIL or
    NINJA_PASSWORD aren't set.
    """
    email = os.getenv("NINJA_EMAIL")
    password = os.getenv("NINJA_PASSWORD")
    if not email or not password:
        logger.info("NINJA_EMAIL/NINJA_PASSWORD not set — skipping ninja user creation")
        return

    from src.db.session import SessionLocal
    from src.db.repositories.users import get_user_by_email
    from src.auth.security import SecurityUtils

    db = SessionLocal()
    try:
        existing = get_user_by_email(db=db, email=email)
        if existing:
            if not existing.is_ninja:
                existing.is_ninja = True
                db.commit()
                logger.info("Marked existing user %s as ninja", email)
            return
        from src.db.models import User
        ninja = User(
            name="Ninja",
            email=email,
            password_hash=SecurityUtils.hash_password(password),
            email_verified=True,
            is_ninja=True,
        )
        db.add(ninja)
        db.commit()
        logger.info("Created ninja user (%s)", email)
    finally:
        db.close()


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

    if os.getenv("ENV", "").lower() != "test":
        try:
            _ensure_ninja_user()
        except Exception as e:
            logger.warning(f"Failed to ensure ninja user: {e}")

    deletion_sweep_task = None
    if os.getenv("ENV", "").lower() != "test":
        from src.jobs.account_deletion import run_account_deletion_sweep
        deletion_sweep_task = asyncio.create_task(run_account_deletion_sweep())

    yield

    # Shutdown: Cleanup if needed
    if deletion_sweep_task:
        deletion_sweep_task.cancel()
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
app.include_router(ninja.router)
