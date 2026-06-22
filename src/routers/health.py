from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.deps.db import get_db
from src.db import sql
import logging

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/")
async def health_check(db: Session = Depends(get_db)):
    """Overall health check. Returns 200 if all critical services are up."""
    checks = {}
    overall_ok = True

    try:
        stmt = sql.select(sql.text("1"))
        with db.begin():
            db.execute(stmt)
        checks["database"] = {"status": "ok"}
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        checks["database"] = {"status": "error"}
        overall_ok = False

    try:
        from src.classes.ollama_connector import OllamaConnector
        response = OllamaConnector.ollama.list()
        # Handle both dict and object responses
        models = response.get('models', []) if isinstance(response, dict) else getattr(response, 'models', [])
        if models:
            checks["ollama"] = {"status": "ok", "models": len(models)}
        else:
            checks["ollama"] = {"status": "error"}
            overall_ok = False
    except Exception as e:
        logger.error(f"Ollama health check failed: {e}")
        checks["ollama"] = {"status": "error"}
        overall_ok = False

    status_code = 200 if overall_ok else 503
    return {
        "status": "ok" if overall_ok else "degraded",
        "checks": checks,
        "status_code": status_code,
    }
