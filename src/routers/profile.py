from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from src.deps.db import get_db
from src.deps.auth import get_current_user
from src.db.repositories.profile import (
    get_profile,
    upsert_profile,
    delete_profile,
    AGE_BANDS,
    TREATMENT_STATUSES,
)

router = APIRouter(prefix="/profile", tags=["profile"])


def _profile_to_dict(profile) -> dict:
    return {
        "exists": True,
        "cancer_type": profile.cancer_type,
        "stage": profile.stage,
        "biomarkers": profile.biomarkers,
        "age_band": profile.age_band,
        "treatment_status": profile.treatment_status,
    }


@router.get("/me")
def get_my_profile(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    profile = get_profile(db, current_user.id)
    if profile is None:
        return {"exists": False}
    return _profile_to_dict(profile)


class ProfileRequest(BaseModel):
    # All fields optional and independently omittable — "Skip" sends none of
    # them, and the row still gets created (see upsert_profile). Length caps
    # match the DB columns so an oversized value 422s rather than reaching
    # the database and failing there.
    cancer_type: str | None = Field(default=None, max_length=255)
    stage: str | None = Field(default=None, max_length=255)
    biomarkers: str | None = Field(default=None, max_length=2000)
    age_band: str | None = None
    treatment_status: str | None = None


@router.put("/me")
def update_my_profile(
    req: ProfileRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # exclude_unset distinguishes "field omitted" (leave existing value
    # alone) from "field explicitly sent" (even as null) — a plain
    # model_dump() can't tell those apart, since both come out as None.
    # A "Skip" sends {} — no fields set, but upsert_profile still creates
    # the (all-null) row, which is what stops onboarding from resurfacing.
    payload = req.model_dump(exclude_unset=True)

    if payload.get("age_band") not in (None, *AGE_BANDS):
        raise HTTPException(status_code=422, detail=f"age_band must be one of {AGE_BANDS}")
    if payload.get("treatment_status") not in (None, *TREATMENT_STATUSES):
        raise HTTPException(status_code=422, detail=f"treatment_status must be one of {TREATMENT_STATUSES}")

    # An explicit "" (a cleared text field) means the same as null here.
    fields = {k: (None if v == "" else v) for k, v in payload.items()}

    profile = upsert_profile(db, current_user.id, **fields)
    return _profile_to_dict(profile)


@router.delete("/me")
def clear_my_profile(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    delete_profile(db, current_user.id)
    return {"ok": True}
