from .router import concept, intervention
import logging


logger = logging.getLogger(__name__)

def get_text_from_results(results: list, field: str) -> list:
  extracted = []
  for x in results:
    if not isinstance(x, dict):
      continue
    # OpenSearch hit shape
    if '_source' in x and isinstance(x.get('_source'), dict):
      val = x['_source'].get(field)
    else:
      # already-flattened shape
      val = x.get(field)
    if isinstance(val, str) and val.strip():
      extracted.append(val)
  logger.info(f"get_text_from_results: extracted {len(extracted)} results for field={field}")
  return extracted


def hybrid_results(intent, claims, sources, k_primary: int = 5, k_secondary: int = 3) -> dict:
  if intent == concept:
    if len(sources + claims) > 5 and len(claims) > 1:
      sources = sources[:k_primary]
      claims = claims[:k_secondary]
    primary = get_text_from_results(sources, 'content_for_embedding')
    secondary = get_text_from_results(claims, 'protocol_claim_en')
    return {
      'primary': primary,
      'secondary': secondary,
      'generation_context': primary + secondary,
      'intent': 'concept'
    }
  elif intent == intervention:
    if len(claims) > 2: 
      claims = claims[:k_primary]
      sources = sources[:k_secondary]
    primary = get_text_from_results(claims, 'protocol_claim_en')
    secondary = get_text_from_results(sources, 'content_for_embedding')
    return {
      'primary': primary,
      'secondary': secondary,
      'generation_context': primary + secondary,
      'intent': 'intervention'
    }
  else:
    raise ValueError(f"Invalid intent: {intent}")