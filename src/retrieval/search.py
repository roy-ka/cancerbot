import logging
import re
from datetime import datetime, timezone

__name__ = 'search'

logger = logging.getLogger(__name__)

# Keep in sync with MIN_FULLTEXT_WORDS in src/routers/conversation_helper.py —
# sources below this are kept in the index (not deleted) but excluded from
# retrieval; see scripts/backfill_full_text_word_count.py for backfilling this
# field on docs indexed before it existed.
MIN_FULLTEXT_WORDS = 20

# Publication types hard-excluded from retrieval. Kept in sync with
# EXCLUDED_PUB_TYPES in src/routers/conversation_helper.py. Applied as a
# `must_not` so docs with no pub_types at all are unaffected.
EXCLUDED_PUB_TYPES = [
  "editorial",
  "comment",
  "published erratum",
  "retracted publication",
  "retraction of publication",
]

# --- Boost weights -----------------------------------------------------------
# These are unmeasured heuristics — tune them here once real query behaviour
# has been observed. They only ever *add* score to an already-matching
# document (they live in `should`, never in `filter`), so a source missing
# these fields is ranked lower but never excluded.
EVIDENCE_BOOST = 1.5        # applied to high-evidence sources (meta-analyses, RCTs)
HIGH_EVIDENCE_MIN = 4       # evidence_level >= this counts as "high"
MID_EVIDENCE_BOOST = 0.6    # smaller nudge for trials/cohort studies
MID_EVIDENCE_MIN = 3
DISEASE_AREA_BOOST = 1.0    # source's disease area matches the query's
RECENT_BOOST = 1.2          # published within RECENT_YEARS
RECENT_YEARS = 5
SEMI_RECENT_BOOST = 0.5     # published within SEMI_RECENT_YEARS
SEMI_RECENT_YEARS = 10


def _scoring_clauses(disease_areas=None):
  """Pure-boost clauses: they raise the score of matching docs but never
  decide whether a doc matches (that's the `must` block in search_sources).

  Every clause targets a field that older documents simply don't have. Because
  they're `should` clauses, a doc without the field just misses the boost —
  it is never filtered out. This is deliberate: an earlier version of this
  module used a positive `range` filter on full_text_word_count, which
  silently made the entire pre-existing corpus unreachable until it was
  backfilled.
  """
  current_year = datetime.now(timezone.utc).year
  clauses = [
    {"range": {"evidence_level": {"gte": HIGH_EVIDENCE_MIN, "boost": EVIDENCE_BOOST}}},
    {"range": {"evidence_level": {"gte": MID_EVIDENCE_MIN, "boost": MID_EVIDENCE_BOOST}}},
    {"range": {"pub_year": {"gte": current_year - RECENT_YEARS, "boost": RECENT_BOOST}}},
    {"range": {"pub_year": {"gte": current_year - SEMI_RECENT_YEARS, "boost": SEMI_RECENT_BOOST}}},
  ]
  if disease_areas:
    clauses.append({
      "terms": {
        "disease_areas": [a.strip().lower() for a in disease_areas if a and a.strip()],
        "boost": DISEASE_AREA_BOOST,
      }
    })
  return clauses


def search_sources(db, text=None, vector=None, k_results: int = 5, disease_areas=None):
  try:
    knn_query = {
        "knn": {
          "embedding": {
            "vector": vector,
            "k": k_results * 4,
            'boost': 2
          },
        }
      }
    text_query = [{
      "match": {
        "content_for_embedding": {
          'query': text,
          'boost': 1
        },
      },
    },{
      "match": {
        "title": {
          'query': text,
          'boost': 1.5
        },
      },
    }]
    match_clauses = []
    if vector:
      match_clauses.append(knn_query)
    if text:
      match_clauses += text_query

    # Matching lives in `must` (a nested bool), scoring in the outer `should`.
    # Keeping them separate matters: with everything flat under `should` +
    # minimum_should_match=1, a doc could qualify on a *boost* clause alone
    # (e.g. any paper from the last 5 years) and get pulled in despite not
    # matching the query at all.
    # Fetch more than needed so Python-side dedup still yields k_results unique sources.
    # collapse is avoided because source_id may be mapped as text (not keyword) in
    # existing indices, which causes a 400 error.
    body = {
      "size": k_results * 4,
      # Only the fields the caller actually consumes: the prompt builder reads
      # content_for_embedding + id, dedup reads source_id, and the log line
      # reads evidence_level/pub_year. Excluded above all is `embedding` — a
      # 768-float array that is ~15KB of JSON per hit and pure waste to ship
      # back and deserialize on every single query.
      "_source": [
        "id",
        "source_id",
        "content_for_embedding",
        "evidence_level",
        "pub_year",
      ],
      "query": {
        'bool': {
          'must': [
            {'bool': {'should': match_clauses, 'minimum_should_match': 1}}
          ],
          'should': _scoring_clauses(disease_areas),
          'filter': [
            {'range': {'full_text_word_count': {'gte': MIN_FULLTEXT_WORDS}}},
          ],
          'must_not': [
            {'terms': {'pub_types': EXCLUDED_PUB_TYPES}},
          ],
        }
      }
    }

    logger.info("[search] executing: text='%s' vector=%s clauses=%d disease_areas=%s",
                text[:80] if text else None, bool(vector), len(match_clauses), disease_areas)
    result = db.search(
      index_type = 'sources_index',
      body = body
    )
    hits = result.get('hits', {}).get('hits', [])
    total = result.get('hits', {}).get('total', {}).get('value', '?')
    logger.info("[search] returned %d raw hits (total_matching=%s)", len(hits), total)

    # Deduplicate by source_id (chunked docs) or base id (old-format docs)
    seen: set = set()
    deduped: list = []
    for hit in hits:
      src = hit.get('_source', {})
      base_id = src.get('source_id') or re.sub(r':c\d+$', '', src.get('id') or hit.get('_id') or '')
      if base_id and base_id not in seen:
        seen.add(base_id)
        deduped.append(hit)

    deduped = deduped[:k_results]
    logger.info("[search] after dedup: %d unique sources", len(deduped))
    for i, hit in enumerate(deduped):
      src = hit.get('_source', {})
      logger.info("[search]   hit %d: id='%s' source_id='%s' score=%s evidence=%s year=%s",
                  i + 1, src.get('id'), src.get('source_id', '(none)'), hit.get('_score'),
                  src.get('evidence_level', '-'), src.get('pub_year', '-'))

    return deduped
  except Exception as e:
    logger.exception("Search failed for text=%s", text[:100] if text else None)
    return []
