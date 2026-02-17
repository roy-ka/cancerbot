from ollama import Client
from dotenv import load_dotenv
import os
from typing import Any, Mapping, Sequence
import logging


class OllamaConnector:  
  __name__='Ollama_connector'
  
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
  def generate_text(cls, context: Sequence[Any], question: str) -> str:
    """Generate an answer grounded in the provided context.

    Context must be a list of dict / Mapping items with explicit IDs, e.g.
         {
           "id": "SRC_193" or "pmid:12345678" or "C81",
           "content_for_embedding": "...text chunk used for grounding..."
         }
    Only `id` and `content_for_embedding` are used.
    """

    def render_item(item: Any, i: int) -> str:
      if not isinstance(item, Mapping):
        raise ValueError(
          "Context items must be dict-like objects containing 'id' and 'content_for_embedding'."
        )
      logging.info(item)
      # Support OpenSearch hit shape: {"_id": "...", "_source": {...}}
      src = item.get("_source") if isinstance(item.get("_source"), Mapping) else None

      # Extract a stable id from common locations
      raw_id = src.get('id')

      if not raw_id:
        raise ValueError(
          "Context item missing 'id'. Provide item['id'] (recommended) or an OpenSearch hit with '_id'/'_source.id'."
        )

      label = str(raw_id).strip()

      # Extract content_for_embedding from common locations
      text = (
        item.get("content_for_embedding")
        or (src.get("content_for_embedding") if src else None)
        or ""
      )
      text = " ".join(str(text).split())

      # Render ONLY id + content_for_embedding
      return f"[{label}] {text}" if text else f"[{label}]"

    rendered = [render_item(item, i).strip() for i, item in enumerate(context)]
    context_block = "\n".join(rendered)

    if not context_block.strip():
      context_block = "(no context provided)"

    full_prompt = f"""
You are a doctor specializing in cancer research and treatment, metabolism and integrative medicine.
Answer using ONLY the context below.
If the context does not contain the answer, say so.

CITATION RULES:
- When you use a fact, cite it using the bracket IDs exactly as provided in the context, e.g. [SRC_193] or [pmid:12345678] or [C81].
- Do NOT invent new citation IDs.

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
  
