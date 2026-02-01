from dotenv import load_dotenv
import sqlalchemy as sql
from sqlalchemy.orm import sessionmaker
import os

load_dotenv()

DB_URL = os.getenv('POSTGRES_URL', 'postgresql+psycopg://user:password@localhost:5432/mydatabase')
engine = sql.create_engine(DB_URL, echo=True)

SessionLocal = sessionmaker(
  autocommit=False, 
  autoflush=False, 
  expire_on_commit=False,
  bind=engine
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()