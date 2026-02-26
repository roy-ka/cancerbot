from dotenv import load_dotenv
import sqlalchemy as sql
from sqlalchemy.orm import sessionmaker
import os

load_dotenv()

DB_URL = os.getenv('POSTGRES_URL', 'postgresql+psycopg://user:password@localhost:5432/mydatabase')
# This app uses synchronous SQLAlchemy sessions. If env uses asyncpg (for async services),
# normalize to psycopg to avoid greenlet/await errors in sync code paths.
if "+asyncpg" in DB_URL:
    DB_URL = DB_URL.replace("+asyncpg", "+psycopg")

engine = sql.create_engine(
    DB_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(
    autocommit=False, 
    autoflush=False, 
    expire_on_commit=False,
    bind=engine
)
