import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routers import auth, health, conversations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


app = FastAPI()

app.add_middleware(
  CORSMiddleware,
  allow_origins=["http://localhost:5173"],
  allow_credentials=True,
  allow_methods=["*"],
  allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(health.router)
app.include_router(conversations.router)
