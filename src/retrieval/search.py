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

# Weight of the vector clause inside the dense sub-query. Uniform scaling can't
# reorder the dense list on its own, but it does set how much a strong cosine
# match is worth *relative to* the metadata boosts above, which is what this
# number actually controls.
KNN_BOOST = 2
BM25_CONTENT_BOOST = 1
BM25_TITLE_BOOST = 1.5

# Reciprocal Rank Fusion smoothing constant. 60 is the value from the original
# RRF paper and the de-facto default: it flattens the 1/(k+rank) curve enough
# that a single list's top hit doesn't automatically win, while still favouring
# documents both lists rank highly.
RRF_K = 60

# Only the fields the caller actually consumes: the prompt builder reads
# content_for_embedding + id, dedup reads source_id + doi, and the log line
# reads evidence_level/pub_year. Excluded above all is `embedding` — a
# 768-float array that is ~15KB of JSON per hit and pure waste to ship back
# and deserialize on every single query.
SOURCE_FIELDS = [
  "id",
  "source_id",
  "content_for_embedding",
  "evidence_level",
  "pub_year",
  "doi",
]


def _scoring_clauses(disease_areas=None):
  """Pure-boost clauses: they raise the score of matching docs but never
  decide whether a doc matches (that's the `must` block in _sub_query).

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


def _sub_query(match_clauses, size, disease_areas):
  """One half of the hybrid search: the given match clauses plus the shared
  boost/filter/exclusion envelope.

  Matching lives in `must` (a nested bool), scoring in the outer `should`.
  Keeping them separate matters: with everything flat under `should` +
  minimum_should_match=1, a doc could qualify on a *boost* clause alone
  (e.g. any paper from the last 5 years) and get pulled in despite not
  matching the query at all. Both sub-queries carry the same envelope so the
  invariant holds per-list, and fusion never sees a doc that didn't match.
  """
  return {
    "size": size,
    "_source": SOURCE_FIELDS,
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


def _dense_body(vector, size, disease_areas):
  return _sub_query(
    [{"knn": {"embedding": {"vector": vector, "k": size, "boost": KNN_BOOST}}}],
    size,
    disease_areas,
  )


def _lexical_body(text, size, disease_areas):
  return _sub_query(
    [
      {"match": {"content_for_embedding": {"query": text, "boost": BM25_CONTENT_BOOST}}},
      {"match": {"title": {"query": text, "boost": BM25_TITLE_BOOST}}},
    ],
    size,
    disease_areas,
  )


def _base_id(hit):
  """Stable per-source key: source_id on chunked docs, the :cN-stripped id on
  documents indexed before the chunked schema existed."""
  src = hit.get('_source', {})
  return src.get('source_id') or re.sub(r':c\d+$', '', src.get('id') or hit.get('_id') or '')


def _dedupe_chunks(hits):
  """Collapse a ranked list to one best-ranked chunk per source.

  This runs *before* fusion on purpose. If two chunks of the same source take
  ranks 1 and 2, fusing them separately would hand that source two RRF
  contributions and let one chunk-heavy document outrank a source that both
  lists agree on.
  """
  seen: set = set()
  out: list = []
  for hit in hits:
    base_id = _base_id(hit)
    if base_id and base_id not in seen:
      seen.add(base_id)
      out.append((base_id, hit))
  return out


def _rrf_fuse(ranked_lists):
  """Reciprocal Rank Fusion across the per-modality ranked lists.

  Fusion is on *rank*, not score. KNN cosine (roughly 0–2 after its boost) and
  BM25 (unbounded) are not on a comparable scale, so the previous approach —
  summing both into one `should` — let whichever clause happened to produce
  the larger raw numbers dominate a given query. Rank fusion gives each list
  an equal say regardless of its score distribution.
  """
  fused: dict = {}
  for name, hits in ranked_lists:
    for rank, (base_id, hit) in enumerate(_dedupe_chunks(hits), start=1):
      entry = fused.get(base_id)
      if entry is None:
        # First list to surface this source supplies the hit we return. Both
        # lists carry valid chunks of the same source; only the chunk text can
        # differ, and either is a legitimate excerpt to hand the LLM.
        entry = {'hit': hit, 'score': 0.0, 'ranks': {}}
        fused[base_id] = entry
      entry['score'] += 1.0 / (RRF_K + rank)
      entry['ranks'][name] = rank
  return fused


def _dedupe_cross_source(entries):
  """Drop repeats of the same paper reached under different stable ids.

  PubMed and CrossRef routinely return one article as both `pmid:…` and
  `doi:…`, which are distinct source_ids — so without this the LLM can be
  handed the same abstract twice and cite it as two independent sources.
  Documents indexed before `doi` was captured simply carry no DOI and pass
  through untouched.
  """
  seen_dois: set = set()
  out: list = []
  for entry in entries:
    doi = (entry['hit'].get('_source', {}).get('doi') or '').strip().lower()
    if doi:
      if doi in seen_dois:
        logger.info("[search] dropping cross-source duplicate of doi=%s", doi)
        continue
      seen_dois.add(doi)
    out.append(entry)
  return out


def search_sources(db, text=None, vector=None, k_results: int = 5, disease_areas=None):
  """Hybrid retrieval over the sources index.

  Runs the dense (KNN) and lexical (BM25) halves as two independent ranked
  lists in a single msearch round trip, then combines them with Reciprocal
  Rank Fusion. `text` and `vector` are deliberately allowed to describe the
  query differently — the caller embeds the natural question for the vector
  while passing representative terms for BM25.

  Returned hits carry the fused RRF score in `_score` (small, ~0.01–0.03 —
  not a relevance percentage) and their per-list ranks in `_component_ranks`.
  """
  try:
    # Fetch more than needed so chunk dedup, fusion and cross-source dedup
    # still leave k_results unique sources.
    size = k_results * 4

    requests = []
    if vector:
      requests.append(('dense', _dense_body(vector, size, disease_areas)))
    if text:
      requests.append(('lexical', _lexical_body(text, size, disease_areas)))
    if not requests:
      logger.warning("[search] called with neither text nor vector — nothing to search")
      return []

    logger.info("[search] executing: text='%s' vector=%s lists=%s disease_areas=%s",
                text[:80] if text else None, bool(vector),
                [name for name, _ in requests], disease_areas)

    responses = db.msearch(
      index_type='sources_index',
      bodies=[body for _, body in requests],
    )

    ranked_lists = []
    for (name, _), response in zip(requests, responses or []):
      # msearch reports per-sub-query failures inline rather than raising, so
      # one bad half degrades to single-modality search instead of losing both.
      if not isinstance(response, dict) or response.get('error'):
        logger.warning("[search] %s sub-query failed: %s",
                       name, (response or {}).get('error') if isinstance(response, dict) else response)
        continue
      hits = response.get('hits', {}).get('hits', [])
      total = response.get('hits', {}).get('total', {}).get('value', '?')
      logger.info("[search] %s returned %d raw hits (total_matching=%s)", name, len(hits), total)
      ranked_lists.append((name, hits))

    if not ranked_lists:
      logger.warning("[search] every sub-query failed")
      return []

    fused = _rrf_fuse(ranked_lists)
    entries = sorted(fused.values(), key=lambda e: e['score'], reverse=True)
    logger.info("[search] fused %d unique sources from %d list(s)", len(entries), len(ranked_lists))

    entries = _dedupe_cross_source(entries)[:k_results]

    results = []
    for entry in entries:
      hit = entry['hit']
      # The per-modality raw score is meaningless post-fusion — replace it so
      # downstream consumers (search_analytics) record the fused score.
      hit['_score'] = entry['score']
      hit['_component_ranks'] = entry['ranks']
      results.append(hit)

    for i, hit in enumerate(results):
      src = hit.get('_source', {})
      logger.info("[search]   hit %d: id='%s' source_id='%s' rrf=%.5f ranks=%s evidence=%s year=%s",
                  i + 1, src.get('id'), src.get('source_id', '(none)'), hit.get('_score'),
                  hit.get('_component_ranks'), src.get('evidence_level', '-'), src.get('pub_year', '-'))

    return results
  except Exception:
    logger.exception("Search failed for text=%s", text[:100] if text else None)
    return []
