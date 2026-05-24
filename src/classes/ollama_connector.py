from ollama import Client, ResponseError
from dotenv import load_dotenv
import os
import re
import json
from typing import Any, Mapping, Sequence
from src.db.models import Message
import logging

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

  _resolved_gen_model: str | None = None

  @classmethod
  def _resolve_gen_model(cls) -> str:
    if cls._resolved_gen_model:
      return cls._resolved_gen_model
    model = (cls.gen_model or '').strip()
    if not model:
      candidates = cls._candidate_gen_models()
      if not candidates:
        raise ValueError(
          "No generation model configured. Set GEN_MODEL_NAME or install a local model (e.g. `ollama pull llama3.1`)."
        )
      model = candidates[0]
    cls._resolved_gen_model = model
    return model

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
  def generate_text(cls, context: Sequence[Any], question: str, history: Sequence[Message]) -> str:
    
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
      """Extract compact ids (and optional names) from msg.sources."""
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

    logger = logging.getLogger(cls.__name__)
    logger.info(f"[generate] question='{question[:120]}'")

    recent_msgs = list(history)

    # Drop assistant messages that are purely JSON blobs (not real responses)
    def _is_tool_output(msg: Message) -> bool:
      if msg.role != 'assistant':
        return False
      content = str(getattr(msg, 'content', '') or '').strip()
      return content.startswith('{') and content.endswith('}') and len(content) > 200

    recent_msgs = [m for m in recent_msgs if not _is_tool_output(m)]
    logger.info(f"[generate] history={len(recent_msgs)} messages after filtering")

    message_context_compact = [
      {
        'role': msg.role,
        'content': _truncate(msg.content, 360 if msg.role == 'user' else 520),
        # Keep only small id lists (enriched content already appears in Scientific Evidence)
        'source_ids': _ids_only(getattr(msg, 'sources', None)),
      }
      for msg in recent_msgs
    ]

    # Compact JSON string for the prompt (stable and token-efficient)
    message_context = json.dumps(message_context_compact, ensure_ascii=False, separators=(',', ':'))

    # If the user explicitly references a source ID from a previous answer (e.g. [pmid:123]),
    # inject those sources at the front of the context so the LLM can elaborate on them.
    referenced_ids = {m.lower() for m in re.findall(r'\[([^\]]+)\]', question)}
    if referenced_ids:
      injected: list[dict] = []
      seen_injected: set[str] = set()
      for msg in reversed(recent_msgs):
        if msg.role != 'assistant':
          continue
        for item in (getattr(msg, 'sources', None) or []):
          item_id = str(item.get('id') or '').strip()
          if item_id.lower() in referenced_ids and item_id not in seen_injected:
            text = item.get('text') or item.get('content_for_embedding') or ''
            if text:
              injected.append({'id': item_id, 'content_for_embedding': text})
              seen_injected.add(item_id)
      if injected:
        logger.info(f"[generate] injecting {len(injected)} explicitly referenced sources: {[i['id'] for i in injected]}")
      context = injected + list(context or [])

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

    try:
      rendered = [render_item(item, i).strip() for i, item in enumerate(safe_context)]
      context_block = "\n".join(rendered)
      logger.info(f"[generate] context_items={len(rendered)} alias_map={alias_to_id}")
    except ValueError as e:
      logger.error(f"[generate] Failed to render context: {e}")
      context_block = "(context unavailable)"

    if not context_block.strip():
      context_block = "(no context provided)"

    history_section = (
        f"\nConversation History:\n{message_context}\n"
        if recent_msgs else ""
    )

    full_prompt = f"""
You are a doctor specializing in cancer research and treatment, metabolism, and integrative medicine.

Use ONLY the Scientific Evidence below as factual grounding.
{"Conversation History is for user intent and context only; it is NOT evidence unless explicitly cited from Scientific Evidence." if recent_msgs else ""}

If fewer than 2 citations support the answer, write: "Insufficient evidence in provided context."

CITATION RULES:
- Cite each factual, mechanistic, outcome, or statistical claim using ONLY the bracket aliases shown in Scientific Evidence: [R1], [R2], [R3], ...
- Place citations immediately after the sentence they support.
- Multiple citations are allowed, e.g. [R1][R3].
- Do NOT invent new citation IDs and do NOT output any other bracket IDs.
- If the evidence conflicts, summarize both sides and cite both.

Scientific Evidence:
{context_block}
{history_section}
QUESTION:
{question}

ANSWER:
""".strip()

    primary = cls._resolve_gen_model()
    candidates = [primary]
    last_error: Exception | None = None
    response = None
    ollama_options = {
      "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "2048")),
      "num_predict": int(os.getenv("OLLAMA_NUM_PREDICT", "384")),
      "temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.2")),
    }

    logger.info(f"[generate] model={primary} options={ollama_options} prompt_chars={len(full_prompt)}")
    logger.debug(f"[generate] prompt=\n{'-'*60}\n{full_prompt}\n{'-'*60}")

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
          logger.warning(f"[generate] model '{model}' unavailable: {e}")
          last_error = e
          continue
        logger.error(f"[generate] Ollama error: {e}")
        last_error = e
        raise ValueError("Model error. Please try again in a moment.")
      except (ConnectionError, TimeoutError, OSError) as e:
        logger.error(f"[generate] Connection error to Ollama: {e}")
        last_error = e
        raise ValueError("Service unavailable. Please try again in a moment.")

    if response is None:
      available = cls._available_models()
      raise ValueError(
        f"No Ollama model available for text generation. Tried: {candidates or [primary]}. "
        f"Installed models: {available or '[]'}. Last error: {last_error}"
      )

    answer = response["response"]
    eval_count = response.get("eval_count") if isinstance(response, dict) else getattr(response, "eval_count", None)
    logger.info(f"[generate] done: answer_chars={len(answer)} eval_tokens={eval_count}")
    logger.debug(f"[generate] answer=\n{answer}")

    # Replace alias citations with the original stable IDs.
    # Example: [R8] -> [url:86cc...]
    for alias, original_id in alias_to_id.items():
      answer = answer.replace(f"[{alias}]", f"[{original_id}]")

    return answer
