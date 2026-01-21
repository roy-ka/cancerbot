from .router import concept, intervention

def hybrid_results(intent, claims, sources):
  if intent == concept:
    return sources + claims
  elif intent == intervention:
    return claims + sources
  else:
    raise ValueError(f"Invalid intent: {intent}")