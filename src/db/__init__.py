from dotenv import load_dotenv
import sqlalchemy as sql
from sqlalchemy.orm import Session
import os

load_dotenv()

DB_URL = os.getenv('POSTGRES_URL', 'postgresql+psycopg://user:password@localhost:5432/mydatabase')
engine = sql.create_engine(DB_URL, echo=True)
session = Session(engine)
stmt = sql.select(sql.text("1"))
with session.begin():
    result = session.execute(stmt)
    for row in result:
        print(row)
print("Database connection established successfully.")