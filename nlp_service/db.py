from typing import AsyncGenerator
from dotenv import load_dotenv
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

load_dotenv()
DATABASE_URL = os.getenv("NLP_DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("NLP_DATABASE_URL/DATABASE_URL/POSTGRES_URL is not set")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

__all__ = ["engine", "SessionLocal", "get_session"]

SessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
