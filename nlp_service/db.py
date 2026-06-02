from typing import AsyncGenerator
from dotenv import load_dotenv
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

load_dotenv()

# Build DATABASE_URL from individual environment variables
postgres_user = os.getenv("POSTGRES_USER", "cancerbot")
postgres_password = os.getenv("POSTGRES_PASSWORD", "")
postgres_host = os.getenv("POSTGRES_HOST", "localhost")
postgres_port = os.getenv("POSTGRES_PORT", "5432")
postgres_db = os.getenv("POSTGRES_DB", "cancerbot")

DATABASE_URL = f"postgresql+asyncpg://{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db}"

if not postgres_password:
    raise RuntimeError("POSTGRES_PASSWORD is not set")

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
