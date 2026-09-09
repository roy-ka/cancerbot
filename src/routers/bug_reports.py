from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from src.deps.db import get_db
from src.deps.auth import get_current_user
from src.db.models import BugReport
import logging

router = APIRouter(prefix="/bug-reports", tags=["bug-reports"])
logger = logging.getLogger(__name__)


class BugReportRequest(BaseModel):
    # title is capped to the column width (String(255)); anything longer used to
    # reach the database and fail there as a 500 rather than a validation error.
    title: str = Field(..., max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    how_to_reproduce: str | None = Field(default=None, max_length=5000)
    report_type: Literal["bug", "feedback"] = "bug"


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
        report_type=req.report_type,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    logger.info("%s created by user %s: %s", req.report_type, current_user.id, req.title)
    return {"ok": True, "id": str(report.id)}
