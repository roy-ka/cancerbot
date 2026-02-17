from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.deps.db import get_db
from src.db import sql
router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/health/db")
async def health_db(db: Session = Depends(get_db)):
    stmt = sql.select(sql.text("1"))
    with db.begin():
        result = db.execute(stmt)
        return {"status": "ok", "result": [row[0] for row in result]}


@router.get("/health/conversations/")
async def debug_conversations(db: Session = Depends(get_db)):
    stmt = sql.text("SELECT COUNT(*) FROM conversations")
    with db.begin():
        count = db.execute(stmt).scalar_one()
    return {"conversations_count": int(count)}
