from typing import AsyncGenerator
from dotenv import load_dotenv
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

load_dotenv()
DATABASE_URL = os.getenv("NLP_DATABASE_URL")

if DATABASE_URL:
    # Expand variable placeholders in the URL
    for key, value in os.environ.items():
        placeholder = "${" + key + "}"
        DATABASE_URL = DATABASE_URL.replace(placeholder, value)
else:
    raise RuntimeError("NLP_DATABASE_URL not set")

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
