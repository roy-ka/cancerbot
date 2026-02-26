from ollama import Client, ResponseError
from dotenv import load_dotenv
import os
import json
from typing import Any, Mapping, Sequence
from src.db.models import Conversation, Message

class OllamaConnector:  
  __name__='Ollama_connector'
  
  load_dotenv()
  ollama_host = os.getenv('OLLAMA_URL', 'http://localhost:11434')
  embed_model = (os.getenv('EMBED_MODEL_NAME', os.getenv('MODEL_NAME')) or '').strip().strip("\"'")
  gen_model = (os.getenv('GEN_MODEL_NAME') or '').strip().strip("\"'")
  ollama = Client(
      host=ollama_host  
  )

  @classmethod
  def _available_models(cls) -> list[str]:
    try:
      listed = cls.ollama.list()
      models = getattr(listed, "models", None) or listed.get("models", [])
      names: list[str] = []
      for m in models:
        name = (
          getattr(m, "model", None)
          or getattr(m, "name", None)
          or (m.get("model") if isinstance(m, dict) else None)
          or (m.get("name") if isinstance(m, dict) else None)
        )
        if isinstance(name, str) and name.strip():
          names.append(name.strip())
      return names
    except Exception:
      return []

  @classmethod
  def _resolve_gen_model(cls) -> str:
    model = (cls.gen_model or '').strip()
    if model:
      return model
    candidates = cls._candidate_gen_models()
    if candidates:
      return candidates[0]
    raise ValueError(
      "No generation model configured. Set GEN_MODEL_NAME or install a local model (e.g. `ollama pull llama3.1`)."
    )

  @classmethod
  def _is_embedding_model(cls, model_name: str) -> bool:
    name = (model_name or "").lower()
    return (
      "embed" in name
      or "nomic-embed" in name
      or name.startswith("mxbai-embed")
      or name.startswith("all-minilm")
    )

  @classmethod
  def _candidate_gen_models(cls) -> list[str]:
    available = cls._available_models()
    return [m for m in available if not cls._is_embedding_model(m)]
  
  @classmethod
  def embed_text(cls, text):
    response = cls.ollama.embed(model=cls.embed_model, input=text)
    return response.embeddings[0]

  @classmethod
  def generate_text(cls, context: Sequence[Any], question: str, conversation: Conversation) -> str:
    
    """Generate an answer grounded in the provided context.

    Context must be a list of dict / Mapping items with explicit IDs, e.g.
         {
           "id": "SRC_193" or "pmid:12345678" or "C81" or "url:<sha1>",
           "content_for_embedding": "...text chunk used for grounding..."
         }

    To avoid LLM typos on long opaque IDs (especially url:<sha1>), the prompt uses
    short alias IDs like [R1], [R2] for citations, and the returned answer is
    post-processed to replace [R#] back to the original stable IDs.
    """

    alias_to_id: dict[str, str] = {}

    def _truncate(s: str, n: int = 320) -> str:
      s = ' '.join(str(s or '').split())
      return (s[:n] + '…') if len(s) > n else s

    def _ids_only(items, max_items: int = 6):
      """Extract compact ids (and optional names) from msg.sources/msg.claims."""
      if not items:
        return []
      out = []
      try:
        for it in items:
          if isinstance(it, dict):
            _id = it.get('id')
            name = it.get('name')
            if _id is None:
              continue
            out.append({'id': str(_id), **({'name': str(name)} if name else {})})
          else:
            # If it's already an id-like primitive
            out.append({'id': str(it)})
          if len(out) >= max_items:
            break
      except Exception:
        return []
      return out

    # Keep only the most recent messages to avoid token bloat
    max_history = int(os.getenv('PROMPT_MAX_HISTORY', '8'))
    recent_msgs = list(conversation.messages)[-max_history:]

    # Drop assistant messages that are purely tool output (e.g., raw JSON blobs)
    def _is_tool_output(msg: Message) -> bool:
      if msg.role != 'assistant':
        return False

      content = str(getattr(msg, 'content', '') or '').strip()

      # Explicit tool intent flag
      if getattr(msg, 'intent', None) == 'tool':
        return True

      # Heuristic: large JSON-like payloads
      if content.startswith('{') and content.endswith('}') and len(content) > 200:
        return True

      return False

    recent_msgs = [m for m in recent_msgs if not _is_tool_output(m)]

    message_context_compact = [
      {
        'role': msg.role,
        'content': _truncate(msg.content, 360 if msg.role == 'user' else 520),
        # Keep only small id lists (enriched content already appears in Scientific Evidence)
        'source_ids': _ids_only(getattr(msg, 'sources', None)),
        'claim_ids': _ids_only(getattr(msg, 'claims', None)),
      }
      for msg in recent_msgs
    ]

    # Compact JSON string for the prompt (stable and token-efficient)
    message_context = json.dumps(message_context_compact, ensure_ascii=False, separators=(',', ':'))

    # Bound evidence size to avoid OOM / runner kills on CPU-only deployments.
    max_context_items = int(os.getenv('OLLAMA_CONTEXT_ITEMS', '8'))
    max_evidence_chars = int(os.getenv('OLLAMA_EVIDENCE_CHARS', '1200'))
    safe_context = list(context or [])[:max_context_items]

    def render_item(item: Any, i: int) -> str:
      if not isinstance(item, Mapping):
        raise ValueError(
          "Context items must be dict-like objects containing 'id' and 'content_for_embedding'."
        )

      # Support OpenSearch hit shape: {"_id": "...", "_source": {...}}
      src = item.get("_source") if isinstance(item.get("_source"), Mapping) else None

      # Extract original stable id (prefer explicit fields; fall back to _source.id; then _id)
      raw_id = (
        item.get('id')
        or item.get('source_id')
        or item.get('claim_id')
        or (src.get('id') if src else None)
        or item.get('_id')
      )

      if not raw_id:
        raise ValueError(
          "Context item missing 'id'. Provide item['id'] or an OpenSearch hit with '_source.id' or '_id'."
        )

      original_id = str(raw_id).strip()

      # Use a short deterministic alias for citations to prevent LLM typos
      alias = f"R{i+1}"
      alias_to_id[alias] = original_id

      # Extract content_for_embedding
      text = (
        item.get('content_for_embedding')
        or (src.get('content_for_embedding') if src else None)
        or ''
      )
      text = ' '.join(str(text).split())
      if len(text) > max_evidence_chars:
        text = text[:max_evidence_chars].rstrip() + "…"

      # Render ONLY alias + content_for_embedding
      return f"[{alias}] {text}" if text else f"[{alias}]"

    rendered = [render_item(item, i).strip() for i, item in enumerate(safe_context)]
    context_block = "\n".join(rendered)

    if not context_block.strip():
      context_block = "(no context provided)"

    full_prompt = f"""
You are a doctor specializing in cancer research and treatment, metabolism, and integrative medicine.

Use ONLY the Scientific Evidence below as factual grounding.
Conversation History is for user intent and context only; it is NOT evidence unless explicitly cited from Scientific Evidence.

If fewer than 2 citations support the answer, write: "Insufficient evidence in provided context."

CITATION RULES:
- Cite each factual, mechanistic, outcome, or statistical claim using ONLY the bracket aliases shown in Scientific Evidence: [R1], [R2], [R3], ...
- Place citations immediately after the sentence they support.
- Multiple citations are allowed, e.g. [R1][R3].
- Do NOT invent new citation IDs and do NOT output any other bracket IDs.
- If the evidence conflicts, summarize both sides and cite both.

Scientific Evidence:
{context_block}

Conversation History:
{message_context}

QUESTION:
{question}

ANSWER:
""".strip()

    primary = cls._resolve_gen_model()
    candidates = [primary] + [m for m in cls._candidate_gen_models() if m != primary]
    last_error: Exception | None = None
    response = None
    ollama_options = {
      "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "2048")),
      "num_predict": int(os.getenv("OLLAMA_NUM_PREDICT", "384")),
      "temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.2")),
    }

    for model in candidates:
      try:
        response = cls.ollama.generate(
          model=model,
          prompt=full_prompt,
          stream=False,
          options=ollama_options,
        )
        break
      except ResponseError as e:
        msg = str(e).lower()
        if "not found" in msg or "does not support generate" in msg:
          last_error = e
          continue
        raise

    if response is None:
      available = cls._available_models()
      raise ValueError(
        f"No Ollama model available for text generation. Tried: {candidates or [primary]}. "
        f"Installed models: {available or '[]'}. Last error: {last_error}"
      )

    answer = response["response"]

    # Replace alias citations with the original stable IDs.
    # Example: [R8] -> [url:86cc...]
    for alias, original_id in alias_to_id.items():
      answer = answer.replace(f"[{alias}]", f"[{original_id}]")

    return answer
