import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routers import auth, health, conversations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


app = FastAPI()

allow_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
allow_origins = [origin.strip() for origin in allow_origins]

app.add_middleware(
  CORSMiddleware,
  allow_origins=allow_origins,
  allow_credentials=True,
  allow_methods=["*"],
  allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(health.router)
app.include_router(conversations.router)
