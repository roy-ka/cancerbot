import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routers import auth, health, conversations
from src.retrieval.db_connector import dbConnector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
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
  allow_methods=["*"],
  allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(health.router)
app.include_router(conversations.router)
