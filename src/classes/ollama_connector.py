from ollama import Client
from groq import Groq
import groq
from google import genai as google_genai
from dotenv import load_dotenv
import os
import re
import json
import logging
from typing import Any, Mapping, Sequence
from src.db.models import Message

logger = logging.getLogger(__name__)

NO_DATA_RESPONSE = "I couldn't find relevant data in my searches."


class _OllamaClientProxy:
  """Lazy proxy for Ollama client (embeddings only)."""
  _client = None

  def _ensure_client(self):
    if _OllamaClientProxy._client is None:
      load_dotenv()
      host = os.getenv('OLLAMA_URL', 'http://localhost:11434')
      _OllamaClientProxy._client = Client(host=host)
    return _OllamaClientProxy._client

  def __getattr__(self, name):
    return getattr(self._ensure_client(), name)


class _GroqClientProxy:
  """Lazy proxy for Groq client (text generation)."""
  _client = None

  def _ensure_client(self):
    if _GroqClientProxy._client is None:
      load_dotenv()
      api_key = os.getenv('GROQ_API_KEY')
      if not api_key:
        raise ValueError("GROQ_API_KEY is not set.")
      _GroqClientProxy._client = Groq(api_key=api_key)
    return _GroqClientProxy._client

  def __getattr__(self, name):
    return getattr(self._ensure_client(), name)


class _GeminiClientProxy:
  """Lazy proxy for Google Gemini client (second-tier fallback)."""
  _client = None

  def _ensure_client(self):
    if _GeminiClientProxy._client is None:
      load_dotenv()
      api_key = os.getenv('GEMINI_API_KEY')
      if not api_key:
        raise ValueError("GEMINI_API_KEY is not set — Gemini fallback unavailable.")
      _GeminiClientProxy._client = google_genai.Client(api_key=api_key)
    return _GeminiClientProxy._client

  def __getattr__(self, name):
    return getattr(self._ensure_client(), name)



class OllamaConnector:
  __name__ = 'Ollama_connector'

  load_dotenv()
  embed_model = os.getenv('EMBED_MODEL_NAME', os.getenv('MODEL_NAME'))
  groq_model = os.getenv('GROQ_MODEL_NAME')
  ollama = _OllamaClientProxy()
  groq = _GroqClientProxy()
  gemini = _GeminiClientProxy()

  @classmethod
  def embed_text(cls, text):
    logger.debug("[ollama] embed model=%s input_len=%d", cls.embed_model, len(text))
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
            out.append({'id': str(it)})
          if len(out) >= max_items:
            break
      except Exception:
        return []
      return out

    max_history = int(os.getenv('PROMPT_MAX_HISTORY', '8'))
    recent_msgs = list(history)[-max_history:]

    def _is_tool_output(msg: Message) -> bool:
      if msg.role != 'assistant':
        return False
      content = str(getattr(msg, 'content', '') or '').strip()
      if getattr(msg, 'intent', None) == 'tool':
        return True
      if content.startswith('{') and content.endswith('}') and len(content) > 200:
        return True
      return False

    recent_msgs = [m for m in recent_msgs if not _is_tool_output(m)]

    message_context_compact = [
      {
        'role': msg.role,
        'content': _truncate(msg.content, 360 if msg.role == 'user' else 520),
        'source_ids': _ids_only(getattr(msg, 'sources', None)),
        'claim_ids': _ids_only(getattr(msg, 'claims', None)),
      }
      for msg in recent_msgs
    ]

    message_context = json.dumps(message_context_compact, ensure_ascii=False, separators=(',', ':'))

    max_evidence_chars = int(os.getenv('OLLAMA_EVIDENCE_CHARS', '900'))

    def render_item(item: Any, i: int) -> str:
      if not isinstance(item, Mapping):
        raise ValueError(
          "Context items must be dict-like objects containing 'id' and 'content_for_embedding'."
        )

      src = item.get("_source") if isinstance(item.get("_source"), Mapping) else None

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

      alias = f"R{i+1}"
      alias_to_id[alias] = original_id

      text = (
        item.get('content_for_embedding')
        or (src.get('content_for_embedding') if src else None)
        or ''
      )
      text = ' '.join(str(text).split())
      if len(text) > max_evidence_chars:
        text = text[:max_evidence_chars] + '…'

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
- If fewer than 2 sources support the answer, write only: "{NO_DATA_RESPONSE}"

Scientific Evidence:
{context_block}

Conversation History:
{message_context}

QUESTION:
{question}

ANSWER (every sentence must have a [R#] citation):
""".strip()

    if not cls.groq_model:
      raise ValueError(
        "GROQ_MODEL_NAME is not set. Set it to a Groq-hosted model (e.g., llama-3.3-70b-versatile)."
      )

    max_tokens = int(os.getenv('GROQ_MAX_TOKENS', '1024'))

    logger.debug(
      "[groq] generate model=%s max_tokens=%d prompt_len=%d context_items=%d",
      cls.groq_model, max_tokens, len(full_prompt), len(rendered),
    )

    raw_answer = None
    groq_exc = None

    try:
      completion = cls.groq.chat.completions.create(
        model=cls.groq_model,
        messages=[{"role": "user", "content": full_prompt}],
        max_tokens=max_tokens,
      )
      if not completion.choices:
        raise ValueError("Groq returned an empty choices list — possible content-policy rejection.")
      choice = completion.choices[0]
      logger.debug(
        "[groq] response model=%s finish_reason=%s tokens_used=%s",
        completion.model,
        choice.finish_reason,
        getattr(completion.usage, "total_tokens", "?"),
      )
      raw_answer = choice.message.content or ""
    except groq.GroqError as exc:
      groq_exc = exc
      logger.warning("[groq] API error (%s: %s), falling back to Gemini", type(exc).__name__, exc)
      from src.utils.email import send_fallback_alert
      send_fallback_alert(cls.groq_model)

    gemini_exc = None
    if raw_answer is None:
      gemini_model = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")
      try:
        response = cls.gemini.models.generate_content(
          model=gemini_model,
          contents=full_prompt,
          config=google_genai.types.GenerateContentConfig(max_output_tokens=max_tokens),
        )
        raw_answer = response.text or ""
        logger.info("[gemini-fallback] model=%s", gemini_model)
      except Exception as exc:
        gemini_exc = exc
        logger.warning("[gemini-fallback] API error (%s: %s), falling back to OpenAI", type(exc).__name__, exc)

    if raw_answer is None:
      raise ValueError(
        f"AI generation unavailable — Groq: {groq_exc}, Gemini: {gemini_exc}"
      )

    answer = raw_answer
    # Replace alias citations with the original stable IDs.
    for alias, original_id in alias_to_id.items():
      answer = answer.replace(f"[{alias}]", f"[{original_id}]")

    # Remove any empty brackets the LLM generated instead of a valid [R#] alias.
    answer = re.sub(r'\s*\[\]', '', answer)

    return answer
