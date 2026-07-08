from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.deps.db import get_db
from src.deps.auth import get_current_user
from src.db.repositories.terms import get_latest_terms, accept_terms

router = APIRouter(prefix="/terms", tags=["terms"])


@router.get("/latest")
def latest_terms(db: Session = Depends(get_db)):
    terms = get_latest_terms(db)
    if not terms:
        raise HTTPException(status_code=404, detail="No terms found.")
    return {"version": terms.version, "text": terms.text, "created_at": terms.created_at}


@router.post("/accept")
def accept_current_terms(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    terms = get_latest_terms(db)
    if not terms:
        raise HTTPException(status_code=404, detail="No terms found.")
    accept_terms(db, user_id=current_user.id, version=terms.version)
    return {"ok": True, "terms_version": terms.version}
