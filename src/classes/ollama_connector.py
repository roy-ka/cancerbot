from ollama import Client
from dotenv import load_dotenv
import os

class OllamaConnector:  
  load_dotenv()
  ollama_host = os.getenv('OLLAMA_URL', 'http://localhost:11434')
  embed_model = os.getenv('EMBED_MODEL_NAME', os.getenv('MODEL_NAME'))
  gen_model = os.getenv('GEN_MODEL_NAME')
  ollama = Client(
      host=ollama_host  
  )
  
  @classmethod
  def embed_text(cls, text):
    response = cls.ollama.embed(model=cls.embed_model, input=text)
    return response.embeddings[0]

  @classmethod
  def generate_text(cls, context: list[str], question: str) -> str:
    context_block = "\n".join(
        f"[S{i+1}] {txt}" for i, txt in enumerate(context)
    )

    full_prompt = f"""
You are a doctor specializing in cancer research and treatment, metabolism and integrative medicine.
Answer using ONLY the context below.
If the context does not contain the answer, say so.
Cite facts using [S1], [S2], etc.

CONTEXT:
{context_block}

QUESTION:
{question}

ANSWER:
""".strip()

    if not cls.gen_model:
      raise ValueError(
        "GEN_MODEL_NAME is not set. Set it to a chat-capable Ollama model (e.g., llama3.1, qwen2.5)."
      )

    response = cls.ollama.generate(
        model=cls.gen_model,
        prompt=full_prompt,
        stream=False
    )

    return response["response"]