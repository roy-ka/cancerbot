from ollama import Client
from dotenv import load_dotenv
import os
import re
import json
from typing import Any, Mapping, Sequence
from src.db.models import Message

class _OllamaClientProxy:
  """Lazy proxy for Ollama client initialization."""
  _client = None

  def _ensure_client(self):
    if _OllamaClientProxy._client is None:
      load_dotenv()
      host = os.getenv('OLLAMA_URL', 'http://localhost:11434')
      _OllamaClientProxy._client = Client(host=host)
    return _OllamaClientProxy._client

  def __getattr__(self, name):
    return getattr(self._ensure_client(), name)

class OllamaConnector:
  __name__='Ollama_connector'

  load_dotenv()
  ollama_host = os.getenv('OLLAMA_URL', 'http://localhost:11434')
  embed_model = os.getenv('EMBED_MODEL_NAME', os.getenv('MODEL_NAME'))
  gen_model = os.getenv('GEN_MODEL_NAME')
  ollama = _OllamaClientProxy()

  @classmethod
  def embed_text(cls, text):
    response = cls.ollama.embed(model=cls.embed_model, input=text)
    return response.embeddings[0]

  @classmethod
  def generate_text(cls, context: Sequence[Any], question: str, history: Sequence[Message]) -> str:
    
    """Generate an answer grounded in the provided context.

    Context must be a list of dict / Mapping items with explicit IDs, e.g.
         {
           "id": "SRC_193" or "pmid:12345678" or "url:<sha1>",
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
    recent_msgs = list(history)[-max_history:]

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

    max_evidence_chars = int(os.getenv('OLLAMA_EVIDENCE_CHARS', '900'))

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
        text = text[:max_evidence_chars] + '…'

      # Render ONLY alias + content_for_embedding
      return f"[{alias}] {text}" if text else f"[{alias}]"

    max_context_items = int(os.getenv('OLLAMA_CONTEXT_ITEMS', '6'))
    rendered = [render_item(item, i).strip() for i, item in enumerate(context[:max_context_items])]
    context_block = "\n".join(rendered)

    if not context_block.strip():
      context_block = "(no context provided)"

    full_prompt = f"""
You are a doctor specializing in cancer research and treatment, metabolism, and integrative medicine.

Use ONLY the Scientific Evidence below as factual grounding. Do NOT use your training knowledge.
Conversation History is for user intent only; it is NOT evidence.

CRITICAL — CITATION RULES (you MUST follow these):
- Every factual sentence MUST end with a citation: [R1], [R2], [R3], etc.
- Use ONLY the aliases that appear in the Scientific Evidence section below.
- Place the citation immediately after the sentence, before the period or after it.
- Multiple citations allowed: [R1][R2].
- Do NOT invent IDs. Do NOT write sentences without citations.
- If the evidence conflicts, summarize both sides and cite both.
- If fewer than 2 sources support the answer, write only: "I couldn't find relevant data in my searches."

Scientific Evidence:
{context_block}

Conversation History:
{message_context}

QUESTION:
{question}

ANSWER (every sentence must have a [R#] citation):
""".strip()

    if not cls.gen_model:
      raise ValueError(
        "GEN_MODEL_NAME is not set. Set it to a chat-capable Ollama model (e.g., llama3.1, qwen2.5)."
      )

    options: dict = {}
    num_ctx = os.getenv('OLLAMA_NUM_CTX')
    num_predict = os.getenv('OLLAMA_NUM_PREDICT')
    if num_ctx:
      options['num_ctx'] = int(num_ctx)
    if num_predict:
      options['num_predict'] = int(num_predict)

    response = cls.ollama.generate(
        model=cls.gen_model,
        prompt=full_prompt,
        stream=False,
        options=options or None,
    )

    answer = response["response"]

    # Replace alias citations with the original stable IDs.
    # Example: [R8] -> [url:86cc...]
    for alias, original_id in alias_to_id.items():
      answer = answer.replace(f"[{alias}]", f"[{original_id}]")

    # Remove any empty brackets the LLM generated instead of a valid [R#] alias.
    answer = re.sub(r'\s*\[\]', '', answer)

    return answer
