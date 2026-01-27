import logging
from fastapi import FastAPI
from src.retrieval import run_retrieval
from pydantic import BaseModel
from src.classes.ollama_connector import OllamaConnector

class RetrieveRequest(BaseModel):
    message: str


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI()

@app.post("/chat/")
async def chat(req: RetrieveRequest):
    context = run_retrieval(req.message)
    response = OllamaConnector.generate_text(context=context['generation_context'], question=req.message)
    return {"response": response}