# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CancerBot is a Retrieval-Augmented Generation (RAG) chatbot for cancer-related medical information. It uses a hybrid search approach (BM25 + KNN vector search) over a corpus of medical sources and claims in OpenSearch, with Groq (cloud LLM) for generation (Gemini as fallback) and Ollama for embeddings only. On every user message, the system also performs live external search (PubMed, CrossRef, Wikipedia, ClinicalTrials.gov), embeds the results, and indexes them into OpenSearch before retrieval.

## Dependencies

Every library or service added to the codebase must be declared in the appropriate file before use:
- Python packages → `requirements.txt`
- Frontend packages → `client/package.json` (via `npm install <pkg>`)
- Docker services → `docker-compose.yml`

Never import a package or depend on a service that is not listed in the relevant file.

The reverse also matters: `requirements.txt` deliberately does **not** contain
spacy/scispacy/`en_core_sci_sm`/pyspellchecker. All NLP runs in the `nlp-service`
container (`nlp_service/requirements.txt`); `src/nlp/__init__.py` is only an HTTP
client. The backend image is built and run twice (backend + worker), so
the scispaCy stack and its model cost hundreds of MB per container for nothing.
For the same reason `src/utils/utils.py` must stay pandas-free — it's imported by
`main.py`, `auth.py` and `db_connector.py`, so a module-level `import pandas`
loads pandas + numpy into every backend and worker process.

## Email Templates

The active provider is Brevo. Email bodies are version-controlled HTML in this repo, not opaque provider-dashboard IDs: `src/utils/email_templates.py`'s `TEMPLATES` dict holds `{subject, html}` per key, rendered via `render(template_key, **fields)` (`str.format()` placeholders — `name` is HTML-escaped since it's the only field that ever carries user text). `src/utils/email_brevo.py` calls `render()` and POSTs the result to Brevo's API. Add a new email by adding a `_..._HTML` template string and a `TEMPLATES[...]` entry there — never hardcode HTML inline elsewhere.

SendGrid is dormant (kept only in case it's ever reinstated): `_send_sendgrid`/`SENDGRID_EMAIL_TEMPLATES` in `src/utils/email.py` are commented out and unused by any live sender.

## Environment Variables

Every new `.env` entry must also be added to:
- `example.env` — include the actual value if not secret, a placeholder if secret
- `tests/conftest.py` — add a `os.environ.setdefault("VAR", "test-value")` line so tests don't fail in CI due to missing env vars; use a safe dummy value (never a real secret)
- `.github/workflows/test.yml` — add the var under the `env:` section of the `test` job; use the same safe dummy value as conftest

After committing, explicitly remind the user to update their `.env` with the new variable.

## Planning Before Coding

Before editing any file or writing any code, present the user with a clear plan:
- Which files will change and why
- The approach / key decisions
- Any trade-offs or open questions

Wait for the user to confirm the plan before proceeding. Do not start coding until approval is given.

## Code Review Workflow

**Before committing changes, always:**

1. **Ask** - Ask the user for explicit confirmation before creating any commit. Wait for a clear "yes" or "commit". This is a ground rule — it cannot be relaxed or skipped without the user's explicit written approval including a timestamp of when the exception was granted.
2. **Review** - Examine all changed code for correctness, then improve it (remove dead code, simplify logic, fix style)
3. **Fix Security** - Check for vulnerabilities (SQL injection, XSS, command injection, etc.)
4. **Test** - Run the test suite and confirm it passes before committing
5. **Verify** - Test changes work as intended (TypeScript/Python compilation, runtime behavior)
6. **Ask before push** - After committing, ask the user before pushing to remote (`git push`)

```bash
# Run tests
pytest                        # full suite
pytest tests/test_auth.py     # single file
```

This applies to all commits: features, bug fixes, refactoring, migrations, etc.

## Test Coverage Requirements

Every addition (new endpoint, repository function, background job, UI flow, etc.) must ship with:
- **Unit tests** — pytest coverage in `tests/` for backend logic (routers, repositories, jobs), and frontend unit/component tests where applicable.
- **Automation tests** — Playwright E2E coverage in `e2e/tests/` for any new or changed user-facing flow.

Do not consider a feature complete until both are written and passing.

## Commands

### Backend API
```bash
# Install dependencies
pip install -r requirements.txt
pip install -r requirements-test.txt

# Run dev server (port 8000)
uvicorn src.main:app --reload

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
```

### Frontend
```bash
cd client
npm install
npm run dev       # Dev server at http://localhost:5173
npm run build     # Production build
npm run lint      # ESLint
```

### Full Stack (Docker)
```bash
docker-compose up --build
# Default profile starts: OpenSearch cluster (2 nodes on 9200), Dashboards (5601),
#   Ollama (11434), PostgreSQL (5432)
# The FastAPI backend is only included in the 'prod' profile:
docker-compose --profile prod up --build
# The Vite frontend is always run separately (not in Docker)
```

### Data Pipeline
```bash
python -m src.embedding      # Embed documents into OpenSearch via Ollama
```

Abstract fetching (PubMed/CrossRef/Wikipedia/ClinicalTrials.gov) happens live per-query via `src/routers/conversation_helper.py`
during the chat flow — there is no longer a standalone offline enrichment script.

### Backup / Restore
```bash
python scripts/backup_db.py   # Dump PostgreSQL to file (optionally upload to S3)
python scripts/restore_db.py  # Restore from a dump file
bash scripts/daily_backup.sh  # Cron-friendly wrapper for backup
```

### Data Migrations
```bash
python scripts/backfill_chunks.py          # Migrate pre-chunked-schema docs (idempotent; run automatically on deploy)
python scripts/fix_crossref_abstracts.py   # Re-fetch + re-clean all CrossRef sources (manual, one-off; use --dry-run / --limit N)
python scripts/remove_short_sources.py     # Delete indexed sources with full_text < MIN_FULLTEXT_WORDS (manual, one-off; defaults to --dry-run, use --execute / --limit N)
python scripts/backfill_full_text_word_count.py  # Backfill full_text_word_count on docs indexed before it existed (idempotent)
python scripts/backfill_conversation_titles.py   # Regenerate naive first-message-prefix conversation titles via generate_title (idempotent; run automatically on deploy; --dry-run / --limit N)
python scripts/backfill_source_metadata.py       # Re-fetch pub_year/pub_types/evidence_level from PubMed for pmid sources missing them (idempotent; run automatically on deploy; --dry-run / --limit N)
python scripts/remove_duplicate_doi_sources.py   # Delete sources double-indexed under two base_id schemes for the same DOI (manual, one-off; defaults to --dry-run, use --execute / --limit N)
```
`fix_crossref_abstracts.py` is not run automatically by `deploy.sh` — it makes a
live CrossRef + Unpaywall + Ollama round trip per source, so it's meant to be run
by hand when needed rather than on every deploy.

`remove_short_sources.py` is likewise manual/one-off, not run by `deploy.sh`. It
cleans up sources indexed before CrossRef querying added `has-abstract:true` and
before the Wikipedia/general indexing paths enforced a `MIN_FULLTEXT_WORDS` (20)
floor on `content_for_embedding` (see `src/routers/conversation_helper.py`) —
those older sources can have full_text as short as a bare title.

`src/retrieval/search.py` filters retrieval to only docs with
`full_text_word_count >= MIN_FULLTEXT_WORDS` — this keeps short sources in the
index (not deleted) but makes them unreachable by retrieval. **Any doc indexed
before this field existed has no value for it and is therefore excluded by the
filter regardless of its actual length** — `backfill_full_text_word_count.py`
must be run once against every existing deployment before/alongside this
change to avoid making the entire pre-existing corpus unsearchable. It is not
currently wired into `deploy.sh`; unlike `backfill_chunks.py`, whether to run
it automatically on every deploy is worth deciding explicitly since it walks
the whole index each time.

`remove_duplicate_doi_sources.py` is a one-off cleanup for the double-indexing
bug fixed alongside it: `_stable_source_id` prefers `pmid` over `doi`, so the
same real article could be indexed twice — once as `pmid:X` from PubMed, once
as `doi:Y` from CrossRef — since `existing_base_source_ids` only catches an
*exact* base_id match. `existing_doi_base_ids` (`db_connector.py`) now prevents
new duplicates of this kind at index time; this script sweeps out anything
already indexed before that fix. For each DOI reachable under more than one
base_id, it keeps one (same priority `_stable_source_id` itself uses: pmid >
doi > nct > url > src) and deletes the rest. Not wired into `deploy.sh` — a
scan when the fix landed found zero DOIs reachable under more than one
`source_id` at the corpus size then (see the Retrieval section), so this may
find nothing to do; run it by hand if the corpus has grown since.

## Architecture

### Services and Ports
| Component | Entry Point | Port | Notes |
|-----------|-------------|------|-------|
| FastAPI backend | `src/main.py` | 8000 | Docker only with `prod` profile |
| React frontend | `client/src/main.tsx` | 5173 | Always run locally |
| OpenSearch node 1 | Docker | 9200/9600 | 2-node cluster |
| OpenSearch node 2 | Docker | — | Same cluster |
| OpenSearch Dashboards | Docker | 5601 | |
| PostgreSQL | Docker | 5432 | |
| Ollama | Docker | 11434 | |
| NLP microservice | `nlp_service/` | 8100 | Docker only with `prod` profile |
| Redis | Docker | 6379 | arq job queue — see Background Jobs below |
| arq worker | `src/worker.py` | — | Docker only with `prod` profile, no exposed port |

**Port binding**: only the backend (8000) is published on `0.0.0.0`. OpenSearch
(9200/9600), Dashboards (5601), PostgreSQL (5432), the NLP service (8100), and
Redis (6379) are bound to `127.0.0.1` in `docker-compose.yml` — they were reachable from any host
on the network, and the NLP service in particular has no authentication of its
own. They stay published on loopback so a backend running on the host in dev can
still reach them; reaching Dashboards on a remote host now needs an SSH tunnel.
Keep the `127.0.0.1:` prefix when editing those `ports:` entries.

### New Conversation Flow
Frontend first calls `POST /conversations/create/` (lightweight DB-only, returns `{id, title}`), then immediately opens a WebSocket to `/conversations/{id}/add_message/ws`. This ensures stage events fire from the very start instead of the UI freezing on `loading_conversation`.

### Chat Query Flow
1. User message arrives via WebSocket (`/conversations/{id}/add_message/ws`) or HTTP POST (`/conversations/{id}/add_message`)
2. User message is saved to PostgreSQL
3. `src/nlp` calls the NLP microservice (`/extract`) to extract scientific terms and expand them with MeSH synonyms (`extracted_terms` stored on the `Message` row). **This runs exactly once per message**, inside `search_and_embed`, which returns `latest_terms` (the current message's own terms) for `conversations.py` to persist. Do not add a second `_extract_terms_from_message` call in the request path — spell-correction and extraction are each a full scispaCy pipeline pass, and the two used to run twice over identical text
4. **External search** runs in parallel: PubMed (10 results), CrossRef (10 results), Wikipedia (3 results), ClinicalTrials.gov (3 results) queried using NLP-extracted terms (`src/routers/conversation_helper.py`). Wikipedia uses the search API first and picks the most oncology-relevant page from candidates. ClinicalTrials.gov hits the v2 REST API directly (not `pytrials`) and is filtered to `overallStatus=COMPLETED` — this is the *evidence* use case (grounding answers in trial findings); the opt-in *participation* feature (recruiting trials by country/city) is separate and client-side only, see `client/src/components/FindTrialsDialog.tsx`. PubMed and ClinicalTrials share the AND-of-OR-groups boolean query builder (`_build_boolean_term_query`).
5. New external sources are embedded via Ollama (`nomic-embed-text`) and indexed into OpenSearch `sources_index` as **150-word chunks with 40-word overlap**. Each chunk gets `id={base_id}:c{n}`, `source_id={base_id}`, `chunk_index`, `full_text` (original), and `tags` (search terms that retrieved it). Dedup is by `source_id` — if any chunk of a base ID exists, the whole source is skipped. Every chunk in the batch is embedded via `OllamaConnector.embed_texts` (batched, `_EMBED_BATCH_SIZE` per request) and written with a single `dbConnector.bulk_index_to_db` call that refreshes **once** at the end. Do not go back to `embed_text` + `index_to_db(refresh=True)` per chunk here: that was one Ollama round trip and one forced Lucene segment flush per chunk, i.e. dozens of each per chat message. The trailing refresh is what keeps the freshly indexed chunks visible to the retrieval query that runs immediately after.
6. External search results are recorded in `external_search_results` table
7. `src/retrieval/__init__.py:run_retrieval` runs the hybrid search in `search.py:search_sources` on `sources_index`. The dense and lexical halves are issued as **two separate ranked lists in one `msearch`** and combined with **Reciprocal Rank Fusion**; each list is deduped to one chunk per `source_id`, and the fused list is deduped again across sources by DOI. Rather than a fixed top-5, it returns **every fused source whose best chunk clears a cosine-similarity floor (`MIN_COSINE`), capped at `MAX_RESULTS`** — so the count tracks how much the corpus actually covers the query (see the Retrieval section). `run_retrieval` embeds the **natural question** for the dense half while passing the **representative terms** as the lexical query. It runs inline in the caller's worker thread — no separate executor
8. Search analytics recorded in `search_analytics` table
9. `src/classes/ollama_connector.py` builds a prompt with history + context (cited as `[source1]`, `[source2]`, ...) and calls Groq chat completions (`GROQ_MODEL_NAME`). On `groq.GroqError`, falls back to Gemini (`GEMINI_FALLBACK_MODEL`).
10. Post-processing replaces `[source1]` aliases with stable base IDs (`pmid:xxx`, `doi:xxx`, `nct:NCTxxx`, `url:<sha1>`) — the `:cN` chunk suffix is stripped before aliases are built
11. Assistant message + source IDs stored in PostgreSQL
12. WebSocket emits staged events throughout (see below)

### WebSocket Stage Events
`loading_conversation` → `saving_user_message` → `fallback_triggered` → `analyzing_recent_messages` → `extracting_search_terms` → `searching_the_internet` (PubMed/CrossRef/Wikipedia/ClinicalTrials run concurrently, so one event covers all four; per-source counts arrive in `found_sources`) → `found_sources` → `embedding_and_indexing_sources` → `sources_indexed` → `retrieving_context` → `building_prompt` → `generating_answer` → `saving_assistant_message` → `done`

### OpenSearch Indices
- `v1.5_en_nomic-embed-text_index` — sources (768-dim KNN `cosinesimil` via `hnsw`/`lucene` + BM25 on `content_for_embedding`, `title`)
- `v1.5_claims_nomic-embed-text_index` — claims (same structure; exists but not queried in the main retrieval path)

Indices are auto-created on startup via `dbConnector.ensure_all_indexes()`.

**Source document fields (chunked schema):**
- `id` — `{base_id}:c{n}` (e.g. `pmid:12345:c0`) — unique per chunk
- `source_id` — base ID without chunk suffix (e.g. `pmid:12345`) — used for dedup (Python-side, in `search_sources`)
- `chunk_index` — position within source (0-based)
- `full_text` — original full text before chunking
- `content_for_embedding` — this chunk's 150-word window (what gets embedded and sent to LLM)
- `tags` — list of NLP-extracted search terms that retrieved this source
- `pmid`, `doi`, `nct`, `title`, `url`, `source_type`, `abstract_source` — provenance fields (`nct` = ClinicalTrials.gov NCT id; drives the `nct:` stable source id)
- `full_text_word_count` — int; retrieval filters out sources below `MIN_FULLTEXT_WORDS` (20)
- `pub_year` — int; PubMed pub date or CrossRef `published.date-parts`. Drives the recency boost
- `pub_types` — keyword[]; lowercased PubMed publication types (or CrossRef `type`). Drives the exclusion `must_not`
- `evidence_level` — int 0–5 derived from `pub_types` via `EVIDENCE_LEVELS` (5 meta-analysis/systematic review, 4 RCT, 3 trial/cohort, 2 default, 1 case report, 0 editorial/retracted). Unknown types fall back to 2 so an unrecognised type never ranks below an ordinary article
- `disease_areas` — keyword[]; general cancer categories (e.g. `brain cancer`) of the entities that retrieved this source. Sourced from `entity_groups[].category` on the NLP `/extract` response — the backend **cannot** compute these itself, since `nlp_service/synonyms.py:get_category` lives in the separate nlp-service container

### Retrieval
`src/retrieval/search.py:search_sources` runs a hybrid search against `sources_index` only, as **two independent ranked lists fused by rank**, not one blended query:
- **dense sub-query** — KNN vector clause (boost ×2)
- **lexical sub-query** — BM25 on `content_for_embedding` (×1) and `title` (×1.5)

Both are issued in a single `dbConnector.msearch` round trip and carry the *same* envelope, so neither list can surface a doc the other would have excluded:
- `must` — a nested bool holding that list's matching clauses (`minimum_should_match: 1`)
- `should` — pure boosts that raise a matching doc's score but can never make a doc match on their own: `evidence_level`, `pub_year` recency, `disease_areas` overlap with the query's entity categories
- `filter` — `full_text_word_count >= MIN_FULLTEXT_WORDS`
- `must_not` — `pub_types` in `EXCLUDED_PUB_TYPES` (editorials, comments, errata, retractions)

Keeping boosts out of the top-level `should` matters: with everything flat under one `minimum_should_match: 1`, a doc could qualify on a boost clause alone (e.g. merely being recent) without matching the query at all.

**Fusion is RRF, not score addition.** Each list is scored `1/(RRF_K + rank)` and the contributions are summed (`RRF_K = 60`, the standard value). Rank fusion is what makes the two halves comparable: KNN cosine (~0–2 after its boost) and BM25 (unbounded) are on different scales, so summing them raw — the previous design — let whichever clause happened to emit larger numbers dominate a given query. Do not "simplify" this back into a single bool with both clause types under one `should`.
- Returned hits carry the **fused RRF score in `_score`** (small, ~0.01–0.03 — *not* a relevance percentage) and their per-list positions in `_component_ranks`. `search_analytics` stores that fused score raw; see the note on those columns below.
- A sub-query that fails is reported inline by `msearch` rather than raising, so one broken half degrades to single-modality search instead of losing the query.

**Variable result count, gated on a cosine floor — not a fixed top-k.** `search_sources` returns every fused source whose best chunk clears `MIN_COSINE` (0.62), ordered by RRF, capped at `k_results` (default `MAX_RESULTS = 10`). `k_results` is a **cap, not an exact count** — a query the corpus covers richly returns near the cap, a sparse one returns a handful, and a clearly off-topic one returns the single top-ranked source (a deliberate fallback so the LLM is never handed an empty context on a borderline query; it can then answer or decline rather than seeing nothing). `OLLAMA_CONTEXT_ITEMS` (also 10) must stay ≥ `MAX_RESULTS` or the prompt builder re-truncates below the cap.
- **The floor is on cosine similarity to the question, never the RRF score.** RRF is rank-based (~0.01–0.03) and *every* query produces a rank-1 doc regardless of quality, so thresholding RRF would gate on rank, not relevance, and hand back a near-constant count. Cosine actually measures semantic closeness.
- **Cosine is read from a dedicated third `probe` sub-query** issued in the same `msearch` (only when a vector is present). It's a pure-KNN query with **no `should` boosts** — the boosted dense list's `_score` is contaminated by the evidence/recency boosts, so its score is not a clean cosine. The probe keeps the same `filter`/`must_not` envelope so it never surfaces a doc the real query would exclude, fetches only `source_id`/`id`, and is **not fused into the ranking** — it only supplies the floor. OpenSearch Lucene `cosinesimil` returns `_score = (1 + cos) / 2`, inverted by `_score_to_cosine`. Per source, the **max** cosine across its chunks decides.
- `MIN_COSINE = 0.62` was calibrated against the live index: on-topic medical queries score 0.68–0.88, clearly off-topic ones 0.43–0.58. `nomic-embed-text` has a high similarity baseline (~0.4 for anything), so the floor sits deliberately above it. Returned hits carry the gating cosine in `_relevance_cosine`. A lexical-only query (no vector, e.g. a URL-title search) has no probe and is not gated.

**The two halves are given different text on purpose.** `run_retrieval(query, disease_areas, question)` embeds `question` (the user's natural message) for the dense list, while `query` stays the NLP-extracted representative terms for BM25. The terms exist to fix keyword/BM25 behaviour (drug-vs-disease drowning); the embedding model is trained on sentences. Rank fusion is what makes this safe — the lists no longer have to share a query string. The exception is a message that was only a URL, where the fetched page title is used for both.

**`search_analytics` scores are raw floats.** `calculate_search_metrics` stores `_score` unscaled. It used to store `int(score * 100)` on the assumption that scores were 0–1; they never were, so every pre-migration row holds a meaningless ~500–2000 — **exclude rows written before `search_analytics_float_scores` from any tuning analysis.** With RRF scores an `Integer` column would truncate every value to 0, which is why the columns are `double precision`.

**Never request the full `_source`.** Both `search_sources` and
`dbConnector.get_claims_and_sources_by_id` pass an explicit field allowlist, because
every document carries a 768-float `embedding` array that serializes to ~15KB of
JSON. Measured against the live index, the allowlist cut the per-message source
lookup from 59KB to 2.2KB (27×) and a retrieval query from 277KB to 27KB (10×).
`dbConnector.SOURCE_DISPLAY_FIELDS` is the allowlist for message source display —
add to it if the UI starts rendering a new field, but never replace it with
`_source: True`.

**Message source lookups are batched.** `add_claims_and_sources_bulk` resolves a
whole page of assistant messages in one OpenSearch query; `add_claims_and_sources`
is a single-message wrapper around it. `get_messages_by_conversation_id` and
`get_recent_messages` must call the bulk form — looping the single-message version
puts one query per assistant message on every conversation open.

**Boosts must stay `should`/`must_not`, never positive `filter`s.** Most of the corpus predates these fields; a `should` clause just means "no boost" for those docs, whereas a positive filter would make every doc lacking the field silently unreachable — exactly what happened when `full_text_word_count` was first added as a range filter. Boost weights are unmeasured heuristics; they're named constants at the top of `search.py` for tuning.
- Works with Lucene-engine KNN (OpenSearch 3); requires `source_id` to be a `keyword` field for the Python-side dedup to group chunks reliably
- **Dedup is Python-side, not OpenSearch `collapse`**: each sub-query fetches `k_results * 4` hits and keeps the first chunk per `source_id` (falling back to the `:cN`-stripped `id` for old-format docs); the fused list is cosine-gated (above) and then capped at `k_results`. `collapse` was avoided because on indices where `source_id` is mapped as `text` (not `keyword`) it 400s. Fetching a multiple of `k` is what leaves enough hits to still yield up to `k` unique sources after dedup and gating.
- **Chunk dedup runs per-list, before fusion.** If two chunks of one source take ranks 1 and 2, fusing them separately would award that source two RRF contributions and let a chunk-heavy document outrank a source both lists agree on.
- **Cross-source dedup by DOI runs after fusion**, so the same paper reached as both `pmid:…` and `doi:…` is handed to the LLM once. Docs indexed before `doi` was captured carry none and pass through untouched. `doi` is mapped as `text` in the live index, so this must stay a `_source`-side Python comparison — an aggregation or `collapse` on that field 400s.
- **Caveat**: docs indexed by `embedding.py` before the chunked schema lack `source_id`; dedup falls back to their bare `id`, but they also lack `full_text_word_count` and so are excluded by the retrieval `filter` until `backfill_chunks.py` / `backfill_full_text_word_count.py` migrate them.

**Mapping caveat**: `_ensure_chunk_fields_mapping()` (`db_connector.py`) must not declare `full_text_word_count` — it's already dynamically mapped as `long`, and `put_mapping` is atomic, so declaring it as `integer` makes OpenSearch reject the *entire* request and silently take the other field mappings down with it. Without those, `pub_types`/`disease_areas` fall back to analyzed `text` and exact-match `terms` queries stop working.

### RAG engine — known limitations & improvement opportunities
Deliberate current state and where it's weak, roughly highest-impact first.

1. **No `nomic-embed-text` task prefixes.** `OllamaConnector.embed_text`/`embed_texts` send raw text; nomic is trained to expect `search_document:` on indexed chunks and `search_query:` on queries, and omitting them measurably hurts retrieval. Adopting this means **re-embedding the whole corpus** (doc/query prefixes must match) — do it as a versioned reindex, not in place. This is the largest remaining win and the only one gated on a reindex.
2. **No reranking.** The cosine-gated fused sources (up to `MAX_RESULTS`) go straight to the LLM. Retrieving wider then reranking is the standard precision upgrade, but both routes have a cost here: a cross-encoder pulls a torch-sized dependency into an image the Dependencies section deliberately keeps lean, and an LLM-judge pass adds a Groq round trip to every message. Note the cosine floor is a *relevance gate*, not a reranker — it prunes off-topic sources but doesn't reorder the ones it keeps.
3. **No offline evaluation set.** Boost weights, `RRF_K`, and the question-vs-terms split are all unmeasured heuristics — there is no golden query set, so retrieval changes are argued rather than measured. `search_analytics` now records usable scores (see Retrieval), which is the raw material for building one.
4. **`claims_index` is created + embedded on every startup but never queried.** Either use claims in retrieval or stop maintaining the index.
5. **Chunking is blind fixed-window (150w/40w overlap).** Fine for abstracts (which rarely chunk), but splits trial records and OA full-text mid-sentence; sentence/section-aware chunking would help the longer sources.

**Addressed** (kept here so the reasoning isn't rediscovered): score normalization in `calculate_search_metrics`, additive score blending replaced by RRF, the dense clause now embedding the natural question rather than the joined terms, and cross-source `pmid:`/`doi:` duplicates — all four are described in the Retrieval section. Note the DOI dedup is **preventive**: when it landed, a scan of the live index found 371 sources, 299 distinct DOIs, and *zero* DOIs reachable under more than one `source_id`, so PubMed and CrossRef had not in fact overlapped yet at that corpus size. This is a *retrieval-time* dedup (never hand the LLM the same paper twice) — it doesn't stop the same paper from being *indexed* twice in the first place. That's a separate, later fix: `existing_doi_base_ids` (`db_connector.py`), called from `_embed_and_index_sources` (`conversation_helper.py`) — see the "Data Migrations" section above for the one-off cleanup script (`remove_duplicate_doi_sources.py`) for anything indexed twice before this landed.

### Data Files (`data/`)
- `sources_canonical.jsonl` — deduplicated sources (merged by PMID > DOI > URL > title)
- `sources_for_embedding.jsonl` — derived from canonical, includes `content_for_embedding` field
- `claims_canonical.jsonl` — structured protocol claims with scoring

### Database Models (`src/db/models.py`)
| Model | Table | Purpose |
|-------|-------|---------|
| `User` | `users` | Auth; has `token_version` (incremented on password reset to invalidate old JWTs) |
| `Conversation` | `conversations` | Soft-deletable chat threads; `forked_from_conversation_id`/`forked_from_message_id` set when created via the "split" message option |
| `Message` | `messages` | Has `sources_ids` (JSON) and `extracted_terms` (JSON) |
| `MessageFeedback` | `message_feedback` | Per-user thumbs up/down (`vote` +1/-1) on an assistant message, unique on `(message_id, user_id)` |
| `Token` | `tokens` | Unified table for password-reset, email-verification, account-deletion, and waitlist-invite tokens — see `src/db/repositories/tokens.py` |
| `LoginAttempt` | `login_attempts` | Brute-force tracking (login) |
| `RateLimitEntry` | `rate_limit_entries` | Rate limiting for register (per-IP, 10/h) and forgot-password (per-email, 5/h) |
| `SearchAnalytic` | `search_analytics` | Per-message search metrics |
| `ExternalSearchResult` | `external_search_results` | Records PubMed/CrossRef/Wikipedia/ClinicalTrials fetches |
| `UrlClassificationJob` | `url_classification_jobs` | Queue of URLs pending cancer-relevance classification |
| `WaitlistEntry` | `waitlist_entries` | Emails collected when registration is full (`MAX_USERS`) — see Auth section |

### Key Environment Variables (`.env`)
```
# OpenSearch
OPENSEARCH_URL=https://localhost:9200
OPENSEARCH_INITIAL_ADMIN_PASSWORD=...

# Ollama (embeddings only)
OLLAMA_URL=http://localhost:11434       # dev; set to http://ollama:11434 in Docker prod
EMBED_MODEL_NAME=nomic-embed-text
OLLAMA_CONTEXT_ITEMS=10                # max context sources sent to LLM (matches MAX_RESULTS in search.py)

# NLP microservice
NLP_SERVICE_URL=http://localhost:8100  # http://nlp-service:8100 in Docker prod
OLLAMA_EVIDENCE_CHARS=900              # max chars per evidence chunk

# Groq (text generation)
GROQ_API_KEY=...
GROQ_MODEL_NAME=openai/gpt-oss-120b    # required — do NOT wrap in quotes
GROQ_MAX_TOKENS=1024                   # max tokens to generate

# PostgreSQL
POSTGRES_USER=cancerbot
POSTGRES_DB=cancerbot
POSTGRES_PASSWORD=...
POSTGRES_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}
DOCKER_POSTGRES_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}

# App
JWT_SECRET=...
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60000
CORS_ORIGINS=http://localhost:5173     # comma-separated for multiple origins
PROMPT_MAX_HISTORY=12                  # Conversation turns included in prompt
MAX_USERS=                             # Cap on total registered users; blank/unset = no cap (see Auth section)
ENV=development                        # set to 'production' in prod

# Ninja (privileged admin account — see "Ninja account" below; unset = no ninja user created)
NINJA_EMAIL=...
NINJA_PASSWORD=...

# Email (SendGrid) — required for password reset
SENDGRID_API_KEY=...
EMAIL_FROM=noreply@example.com
EMAIL_FROM_NAME=CancerBot

# Backups — optional S3 upload
BACKUP_S3_BUCKET=...

# Gemini (fallback LLM when Groq is unavailable)
GEMINI_API_KEY=...
GEMINI_FALLBACK_MODEL=gemini-2.5-flash

# Optional integrations
UNPAYWALL_EMAIL=
```

### Auth
JWT tokens (HS256) accepted via `Authorization: Bearer <token>` header or `access_token` cookie. Dependency: `Depends(get_current_user)` in `src/deps/auth.py`.
- **JWT revocation**: tokens carry a `tv` (token version) claim. `User.token_version` is incremented on password reset; tokens with a mismatched `tv` are rejected with 401.
- **Rate limiting**: login uses `LoginAttempt` (5 failures → 15 min lockout); register uses per-IP limit (10/h); forgot-password uses per-email limit (5/h) — both via `RateLimitEntry`.
- **Password reset**: time-limited codes via SendGrid email.
- **Constant-cost login**: `/auth/login/` always performs one `verify_password`, falling back to `_get_dummy_hash()` when the email is unknown. Do not restore the `not user or not verify_password(...)` short-circuit — skipping a 600k-round pbkdf2 for unregistered addresses makes account existence measurable from response latency.
- **`/auth/register/` still discloses whether an email is registered** (400 "Email already registered"). Left deliberate: a generic response needs a "someone tried to register" mail flow, loses a genuinely useful error, and `e2e/global-teardown.ts` depends on it.
- **Stale throttling rows** are pruned every 6h by `src/jobs/auth_cleanup.py`. Both `login_attempts` and `rate_limit_entries` are keyed by attacker-supplied values (any submitted email, any client IP), so they have no natural bound. The sweep never deletes a row whose lock/block is still in the future.
- **WebSocket Origin**: CORSMiddleware does not cover WS handshakes, so `post_message_ws` checks `Origin` against `CORS_ORIGINS` itself. A *missing* Origin is allowed on purpose — browsers always send one, so its absence means a non-browser client with no ambient cookie.
- **`CORS_ORIGINS='*'`** makes `src/main.py` refuse to start in production. Starlette echoes the request Origin when `allow_credentials=True`, so a wildcard lets any site issue authenticated requests with the user's cookie.
- **Client IP**: `_client_ip` in `auth.py` uses the socket peer only. `X-Forwarded-For` is **not** trusted — the backend serves directly on port 8000, so the header is attacker-controlled and honouring it let anyone defeat the per-IP registration limit by rotating a fake value. If a reverse proxy is ever added, re-enable it *only* for requests whose immediate peer is the proxy, and set `MAX_REGISTER_ATTEMPTS` accordingly — otherwise every user shares one rate-limit bucket.
- **Registration cap (slow-growth rollout)**: `MAX_USERS` (blank/unset = no cap) gates new signups. `GET /auth/registration_status/` returns `{"open": bool}` (no count disclosed) so the frontend can show the registration form or a waitlist form; `/auth/register/` re-checks the same cap server-side (403 if full) so a client that skips the status check can't bypass it. `POST /auth/waitlist/` requires `email` and `name`, stores them in `WaitlistEntry`, enqueues a `waitlist_joined` confirmation email using the submitted name, and is listed for the ninja account via `GET /ninja/waitlist/`.
- **Waitlist invites**: the ninja Waitlist tab (`client/src/pages/Ninja.tsx`) has an Invite/Resend invite button per entry — `POST /ninja/waitlist/{id}/invite` calls `tokens.py:create_waitlist_invite_token` (48h TTL, `token_type="waitlist_invite"`) and enqueues a `waitlist_invited` email with a `.../login?invite_token=...` link. A **valid, unexpired invite token bypasses `MAX_USERS`** for that one email — `/auth/register/` accepts an optional `invite_token` field and checks it via `verify_waitlist_invite_token` (which also confirms the token's email matches the submitted one, via `normalize_email_for_dedup`, before allowing the bypass) only when the general cap check fails. `GET /auth/invite_info/?invite_token=...` (read-only, doesn't consume the token) lets `RegistrationForm` pre-fill and lock the email field so what's submitted always matches what the token was issued for. Resending an invite calls `create_waitlist_invite_token` again, which invalidates the previous token outright — only the most recently sent link ever works. A waitlist_invite token is **not** consumed on successful registration (see the Token model note below) — the email-uniqueness check on `/auth/register/` is what prevents reuse for a second signup.
- **Waitlist dedup by email variation**: `src/utils/email_normalize.py:normalize_email_for_dedup` canonicalizes an email for duplicate-detection only (lowercase, strip a `+tag` for any provider, and for gmail.com/googlemail.com also strip dots from the local part and fold both domains to `gmail.com`) — never used to actually send mail, since a non-Gmail provider may treat the un-stripped form as a distinct real inbox. `WaitlistEntry.normalized_email` (unique, indexed) stores this form alongside the real `email`; `create_waitlist_entry` looks up by it, so `john.doe+promo@gmail.com` re-submitted as `johndoe@gmail.com` is recognized as the same signup instead of creating a duplicate row. `POST /auth/waitlist/` also rejects (400) a submission whose normalized form matches an *existing user's* email via `users.email_variation_is_registered` — that function scans and normalizes every user's email in Python rather than querying an indexed column, since `User.email` has no normalized counterpart; fine at this project's intentionally small scale, but would need its own stored/indexed column if the user table ever grows large.

### Prompt safety
Retrieved evidence is third-party text (abstracts, trial records, scraped
pages), so `_build_prompt` treats it as untrusted input:

- The evidence block is wrapped in the `_EVIDENCE_BEGIN` / `_EVIDENCE_END`
  markers, and an UNTRUSTED CONTENT section tells the model that anything
  inside is data, never instructions.
- `_EVIDENCE_FENCE_RE` strips any fence marker appearing *within* a source's
  text, so a page containing `===== END UNTRUSTED EVIDENCE =====` cannot close
  the block early and have its remaining text read as top-level instructions.
- The markers carry the `=====` decoration precisely so they stay distinct from
  the prose that describes them — keep it that way, or "exactly one closing
  marker" stops being a checkable property.

This reduces prompt injection; it does not eliminate it. Treat model output
derived from fetched pages as untrusted for anything with side effects.

### XML parsing
All `fromstring` calls go through `defusedxml` (imported as `_safe_fromstring`
in `xml_to_source.py`, `conversation_helper.py` and
`scripts/backfill_source_metadata.py`). Plain `xml.etree.ElementTree` stays
imported alongside it only for `ET.tostring`, which defusedxml does not
provide. Don't switch a parse site back to `ET.fromstring`.

### Outbound fetch safety (SSRF)
Any URL that originates from user input or a third-party API must go through
`_validate_fetch_target` / `_safe_get` in `src/routers/conversation_helper.py`
before a request is made. The rules:

- **`_is_safe_url` is a pre-filter, not a gate.** It only rejects *literal*
  private IPs. A hostname passes it, so `http://nlp-service:8100/`,
  `http://metadata.google.internal/` and public DNS names answering `127.0.0.1`
  all sail through. Never use it alone to guard a fetch.
- **`_validate_fetch_target` resolves the name** and rejects the URL if *any*
  resolved address is private/loopback/link-local/reserved/multicast.
- **`_safe_get` is the only way to fetch an untrusted URL.** It validates the
  target, follows redirects **manually** (max `_MAX_REDIRECTS`), re-validating
  every hop, and streams the body with a `_MAX_FETCH_BYTES` cap. Do not switch
  it back to `follow_redirects=True`: that chases a hop into private space
  without consulting the validator, which is the standard bypass.
- **`fetch_url_contents` validates at its own entry point too.** `req.urls`
  arrives from the request body with only a scheme check, so the gate cannot
  live solely in the message-text path — that was the original hole.
- Fetches to *hardcoded* hosts (NCBI, CrossRef, Unpaywall) don't need the gate;
  only their `doi`/`pmid` path parameters come from user input and those are
  escaped.

Known limitation: addresses are validated before the request and httpx resolves
again on connect, leaving a narrow DNS-rebinding window. Closing it fully needs
the socket pinned to the validated address, which conflicts with TLS hostname
verification.

### NLP
`src/nlp/__init__.py` is a thin HTTP client that calls the **NLP microservice** (`nlp_service/`) over HTTP. The microservice runs scispaCy (`en_core_sci_sm`) + SpellChecker in a separate Docker container (`nlp-service`, port 8100). URL configured via `NLP_SERVICE_URL` env var (default `http://localhost:8100`).
- `extract_terms(text)` → `POST /extract` — entity extraction + abbreviation expansion + MeSH synonym lookup (`nlp_service/synonyms.py`); returns merged term list
- `correct_spelling(text)` → `POST /spelling/correct` — spell correction with protected medical terms
- `load_models()` — no-op; logs the service URL at startup

### Background Jobs (arq)
`src/worker.py` is a separate `arq` worker process (its own `worker` container in
`docker-compose.yml`, `prod` profile), backed by Redis (`REDIS_URL`). It replaced
two different older patterns: hand-rolled `while True: await asyncio.sleep(N)`
loops that ran *inside* the backend web process (account-deletion and
auth-cleanup sweeps), and a standalone polling container (`url-classifier`,
`python -m src.workers.url_classifier`, `SELECT ... FOR UPDATE SKIP LOCKED`
every `URL_CLASSIFIER_POLL_INTERVAL` seconds) — both are gone.

- **`src.queue.enqueue(job_name, **kwargs)`** — how the web process (or another
  job) publishes work. Never raises: a Redis/worker outage must not turn a
  successful request into a 500, so a failed enqueue is logged and swallowed —
  the job simply doesn't run until the queue is back. This mirrors every
  `send_*` helper in `src/utils/email.py` already logging and swallowing
  delivery failures rather than surfacing them to the caller.
- **Cron jobs** (`WorkerSettings.cron_jobs`, `src/worker.py`):
  - `auth_cleanup_sweep` (`src/jobs/auth_cleanup.py`) — every 6h, `run_at_startup=True`
  - `reap_and_requeue_stale_url_classification_jobs` (`src/jobs/url_classification.py`) — every 5 minutes; resets rows stuck in `processing` back to `pending`, then re-enqueues every `pending` row old enough that its own insert-time enqueue has had time to run (the safety net for the case below)
- **On-demand jobs** (`WorkerSettings.functions`):
  - Email: `src/jobs/email_jobs.py` wraps each `src.utils.email.send_*` sender; `src/routers/auth.py`'s email call sites (registration, password reset, account-deletion request/cancel, waitlist join) and `ollama_connector.py`'s Groq-failure fallback alert enqueue these instead of using FastAPI `BackgroundTasks` (which no router uses anymore). `send_account_deleted_email` is the one sender *not* wrapped here — it's only ever called from `delete_scheduled_user_job`, which already runs inside the worker, so there's nothing to enqueue.
  - URL classification: `classify_url_job` (`src/jobs/url_classification.py`) — LLM-classifies a user-provided URL as cancer-related via Groq and, if so, indexes it. `conversation_helper.py`'s `_enqueue_url_classification` still inserts the `url_classification_jobs` row first (it stays the audit/status record — `status`/`llm_reasoning`/`error`/`processed_at` are genuinely useful persisted) and then immediately enqueues `classify_url_job` for it, so classification runs right away instead of waiting for a poll tick. The job claims its row with `FOR UPDATE SKIP LOCKED` scoped to its own id, so a duplicate enqueue of the same job (e.g. racing the reaper) can't double-process it.
  - Account deletion: `delete_scheduled_user_job` (`src/jobs/account_deletion.py`) — **not a cron sweep**. `/auth/confirm-delete/` enqueues it directly via arq's native deferred-execution support (`src.queue.enqueue(..., _defer_until=deletion_date)`), so it fires once, exactly at the 7-day grace-period deadline, instead of an hourly scan of the whole `users` table finding it later. It re-checks `deletion_scheduled_at` at execution time and no-ops if it's `None` (cancelled) or now points to a later date (cancel-then-reschedule) — the correct job is always whichever one was deferred for the *current* value of that column, so nothing needs to explicitly cancel/abort the stale one in Redis. Enqueued with a deterministic `_job_id` (`job_id_for_user`, `delete-user-{id}`) so re-enqueueing the same schedule is a no-op rather than a duplicate. `reschedule_pending_deletions` runs once on worker startup (`WorkerSettings.on_startup`) and re-enqueues (idempotently, same job id) anyone still showing a `deletion_scheduled_at` — the safety net for a deletion scheduled before this job existed, or a deferred job Redis lost (e.g. restarted without persistence).
- **Local dev**: nothing in `WorkerSettings` runs unless a worker process is actually up — running the backend alone (`uvicorn src.main:app --reload`) does not run cron sweeps, deferred jobs, or process enqueued jobs. Run the worker separately if you need that: `arq src.worker.WorkerSettings`.

### Routers (`src/routers/`)
- `auth.py` — registration, login, password reset
- `conversations.py` — CRUD + WebSocket message handling; includes `POST /conversations/create/`
- `health.py` — health check endpoint
- `ninja.py` — admin-only routes gated by `get_current_ninja_user` (`src/deps/auth.py`); see "Ninja account" below

### Ninja account
A single privileged `User` row (`is_ninja=True`), created idempotently on startup from `NINJA_EMAIL`/`NINJA_PASSWORD` env vars (`src/main.py:_ensure_ninja_user`) — no-op if either is unset. Logs in through the normal `/auth/login/` endpoint, but its JWT is always capped at 2 hours regardless of `rememberMe` or the dev-only long-expiry override.

Ninja can browse every user (`GET /ninja/users/`), open any of their conversations (`GET /ninja/users/{id}/conversations/`, `GET /ninja/conversations/{id}/messages/` — the latter includes previously-hidden ninja exchanges for continuity), and post a message into someone else's conversation (`POST /ninja/conversations/{id}/add_message`). That message runs through the exact same search/retrieval/LLM pipeline as a real user message, but both the question and answer are persisted with `Message.hidden_from_user=True`.

`hidden_from_user` messages are excluded by default from `get_messages_by_conversation_id` and `get_recent_messages` (`src/db/repositories/messeges.py`) — the real user's own endpoints and LLM prompt history never see them. This can't be set from a request body (the client-facing `Message` pydantic model has no such field); it's only ever set by `_process_post_message`'s `hidden_from_user` parameter, which only the ninja router passes as `True`.

### Conversation Ordering
Conversations are sorted by `max(message.created_at)` across all roles (see `get_conversations_list_by_user_id` in `src/db/repositories/conversations.py`). `Conversation.updated_at` is **not** bumped when messages are added — do not rely on it for recency ordering.

### OpenSearch — Production SSL
Preferred: set `OPENSEARCH_CA_CERT` to a CA cert generated by `scripts/generate_opensearch_certs.sh` (a self-signed root CA + a node cert covering `opensearch-node1`/`opensearch-node2`/`localhost`, mounted into both containers via `docker-compose.yml`). When set, `src/retrieval/db_connector.py` verifies TLS against that specific CA (`verify_certs=True`, real hostname checking) instead of disabling verification — this is what actually closes the "TLS certificate not verified" gap rather than just silencing the warning. Each environment (local dev, prod) generates and keeps its own CA; the private key (`root-ca-key.pem`) must never be committed (it's gitignored under `certs/`).

Fallback (only when `OPENSEARCH_CA_CERT` is unset): `verify_certs=False` alone is insufficient in production (newer urllib3 still validates), so `db_connector.py` explicitly builds an `ssl.CERT_NONE` context when `is_prod() and not verify_certs`, logging a warning. Do not remove this fallback — it exists for environments that haven't yet been migrated to the CA-pinning setup above.

### Migrations — Idempotency Pattern
New migrations that create tables or indexes must use raw SQL with `IF NOT EXISTS` via `op.execute()`, not `op.create_table()` / `op.create_index()`. This avoids `DuplicateTable` errors when revision IDs change between deploys. See `add_bug_reports_table_001.py` as the canonical example.

### Axiom
Initialised in `src/main.py` and `nlp_service/app.py` via `_init_axiom_logging()` — an `AxiomHandler` is attached to the root logger, forwarding standard Python `logging` calls at INFO+ to the Axiom dataset named by `AXIOM_DATASET`, authenticated via `AXIOM_TOKEN_WRITE`. Both env vars must be set for logging to activate; init is skipped silently (no error) if either is missing. Log records carry no explicit environment tag — the logger `name` field (e.g. `src.main`, `nlp_service.app`) is the only built-in way to distinguish sources when querying.

Querying (not just ingesting) uses a **separate** token, `AXIOM_TOKEN_READ` — Axiom scopes tokens per-action, and the ingest token above does not (and should not) also carry query access. Only `src/jobs/admin_digest.py`'s daily digest queries Axiom (`apl_query`, log volume by level + top errors over the last 24h); it degrades gracefully (logs and returns `None`) if `AXIOM_TOKEN_READ`/`AXIOM_DATASET` are unset or the query fails, rather than blocking the digest from sending.

### Deploy Script (`scripts/deploy.sh`)
- Checks disk free ≥ 100GB before building; runs `docker system prune` and re-checks if low
- Builds with `--pull` so the base image is refreshed when upstream publishes OS patches (e.g. curl CVEs); intermediate layers still cache when the base digest is unchanged
- Scans built images with Trivy (`HIGH`/`CRITICAL`, ignore-unfixed); aborts deploy on findings
- Skips `alembic upgrade heads` if `alembic current` already shows `(head)` — avoids 4 unnecessary Docker container spawns per deploy
- Runs seeds (non-fatal): `seed_wikipedia_tags.py` then `backfill_chunks.py` (scrolls the entire sources index and migrates every doc without a `source_id` field to the chunked schema; idempotent), then `backfill_source_metadata.py` (re-fetches pub_year/pub_types/evidence_level from PubMed for pmid sources missing them; idempotent), then `backfill_conversation_titles.py` (regenerates conversation titles still stuck on the naive first-message-prefix; idempotent)
- Prints git commit hash in the success summary
- **Self re-exec after `git pull`**: the script hashes itself before and after the pull; if `deploy.sh` changed, it re-execs from `$SCRIPT_DIR/deploy.sh` (capped at one re-exec via `DEPLOY_REEXEC_COUNT`) instead of continuing on bash's stale in-memory copy of the old script for the rest of the run. Without this, any step *added to deploy.sh itself* in the commit being pulled would silently never run on the very deploy that introduces it — this bit `backfill_conversation_titles.py`'s first deploy. `DEPLOY_LOG_FILE_OVERRIDE` and `DEPLOY_PREV_GIT_HEAD_OVERRIDE` carry the log file and the true pre-deploy commit (for rollback) across the re-exec.
