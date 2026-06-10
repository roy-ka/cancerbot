from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from src.deps.db import get_db
from src.deps.auth import get_current_user
from src.db.models import BugReport
import logging

router = APIRouter(prefix="/bug-reports", tags=["bug-reports"])
logger = logging.getLogger(__name__)


class BugReportRequest(BaseModel):
    title: str
    description: str | None = None
    how_to_reproduce: str | None = None


@router.post("/")
def create_bug_report(
    req: BugReportRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not req.title.strip():
        raise HTTPException(status_code=422, detail="Title is required")

    report = BugReport(
        user_id=current_user.id,
        title=req.title.strip(),
        description=req.description,
        how_to_reproduce=req.how_to_reproduce,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    logger.info("Bug report created by user %s: %s", current_user.id, req.title)
    return {"ok": True, "id": str(report.id)}
