# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CancerBot is a Retrieval-Augmented Generation (RAG) chatbot for cancer-related medical information. It uses a hybrid search approach (BM25 + KNN vector search) over a corpus of medical sources and claims in OpenSearch, with a single generation provider chosen by `LLM_PROVIDER` (`ollama` — the default — `groq` or `gemini`) and Ollama for embeddings. On every user message, the system also performs live external search (PubMed, CrossRef, Wikipedia, ClinicalTrials.gov), embeds the results, and indexes them into OpenSearch before retrieval.

## Dependencies

Every library or service added to the codebase must be declared in the appropriate file before use:
- Python packages → `requirements.txt`
- Frontend packages → `client/package.json` (via `npm install <pkg>`)
- Docker services → `docker-compose.yml` (plus `docker-compose.prod.yml` for production-only settings — see "OpenSearch — TLS is production-only")

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

The active provider is Brevo. Email bodies are version-controlled HTML in this repo, not opaque provider-dashboard IDs: the `src/utils/email_templates/` package has one module per email, and its `__init__.py`'s `TEMPLATES` dict maps each key to `{subject, html}`, rendered via `render(template_key, **fields)` (`str.format()` placeholders — `name` is HTML-escaped since it's the only field that ever carries user text). `src/utils/email_brevo.py` calls `render()` and POSTs the result to Brevo's API. Add a new email by adding a template module and a `TEMPLATES[...]` entry there — never hardcode HTML inline elsewhere.

Admin-facing mail (the daily/weekly digests) goes to every address in `ADMIN_DIGEST_EMAILS`; unset means those are skipped. Never hardcode a recipient address in code.

SendGrid is dormant (kept only in case it's ever reinstated): `_send_sendgrid` in `src/utils/email.py` is unused by any live sender.

## Environment Variables

Every new `.env` entry must also be added to:
- `example.env` — include the actual value if not secret, a placeholder if secret
- `tests/conftest.py` — add a `os.environ.setdefault("VAR", "test-value")` line so tests don't fail in CI due to missing env vars; use a safe dummy value (never a real secret)
- `.github/workflows/test.yml` — add the var under the `env:` section of the `test` job; use the same safe dummy value as conftest

## Code Review Workflow

**Before committing changes, always:**

1. **Review** - Examine all changed code for correctness, then improve it (remove dead code, simplify logic, fix style)
2. **Fix Security** - Check for vulnerabilities (SQL injection, XSS, command injection, etc.)
3. **Test** - Run the test suite and confirm it passes before committing
4. **Verify** - Test changes work as intended (TypeScript/Python compilation, runtime behavior)
5. **Docs** - If the change affects setup, env vars, commands, services, ports, or architecture, update `README.md` (and this file) in the same change
6. **Server runbook** - If the change affects how the production server is set up or deployed (new or renamed production `.env` variables, host packages, ports, certificates, nginx, compose files, `deploy.sh` steps, startup refusals), update `docs/server-runbook.html` in the same change

```bash
# Run tests
pytest                        # full suite
pytest tests/test_auth.py     # single file
```

This applies to all commits: features, bug fixes, refactoring, migrations, etc.

Contributors may keep personal workflow rules in an untracked `CLAUDE.local.md` (gitignored).

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
docker compose up -d --build
# Default profile starts: OpenSearch (single node on 9200, plain HTTP locally),
#   Dashboards (5601), PostgreSQL (5432), NLP service (8100)
# Production layers docker-compose.prod.yml on top (OpenSearch TLS) and adds the
# 'prod' profile (backend, arq worker, Redis) — scripts/deploy.sh does exactly this:
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile prod up -d --build
# Ollama is NOT in docker-compose — it runs natively on the host (Metal GPU on
# Mac); containers reach it via the host. The Vite frontend always runs separately.
```

### Data Pipeline
The corpus builds itself: every chat message fetches fresh PubMed/CrossRef/Wikipedia/ClinicalTrials.gov results live (`src/routers/conversation_helper.py`) and indexes them, so a new deployment starts with an empty index and grows with use. There is no offline enrichment step.

`python -m src.embedding` is a legacy bulk loader for the original curated corpus; it reads `data/*.jsonl` files that are not part of this repository.

### Backup / Restore
```bash
python scripts/backup_db.py   # Dump PostgreSQL to file (optionally upload to S3)
python scripts/restore_db.py  # Restore from a dump file
python scripts/backup_opensearch.py                       # Export the search indices (mapping + gzipped docs)
python scripts/restore_opensearch.py <date-dir> --replace # Recreate them from an export (0 replicas; --dry-run first). See BACKUP.md for running it in the backend container
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
| OpenSearch | Docker (`opensearch-node1`) | 9200/9600 | Single node (`discovery.type=single-node`, 512 MB heap) — sized for a 4 GB server; indices use 0 replicas |
| OpenSearch Dashboards | Docker | 5601 | |
| PostgreSQL | Docker | 5432 | |
| Ollama | Native on host | 11434 | Embeddings; generation too when `LLM_PROVIDER=ollama`; not in docker-compose |
| NLP microservice | `nlp_service/` | 8100 | Docker, default profile |
| Redis | Docker | 6379 | `prod` profile only; arq job queue — see Background Jobs below |
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
2a. **Personal-question fast path** (`src/routers/conversations.py`, gated on `not hidden_from_user and conversation.use_profile_context` and a *populated* profile): a cheap LLM classification (`OllamaConnector.classify_personal_question`) decides whether the message asks CancerBot to recall the user's own saved profile fields (`cancer_type`/`stage`/`biomarkers`/`age_band`/`treatment_status`) rather than a general medical question. If so, the matching field(s) are recited back **deterministically** (`src/db/repositories/profile.py:render_profile_recall` — never LLM-generated) so a factual "what you told us" answer can never blend into a citation-grounded literature answer in the same generation call. When the classifier also detects a separate general question in the same message, the recall text is prepended to the normal generated answer instead of replacing it — and that answer is searched for and generated from the classifier's `general_question` (the general half, rephrased standalone) rather than the full message, passed as `question_override` to `_answer_via_retrieval` and as `latest_text_override` to `search_and_embed`. The raw message is also dropped from that turn's prompt history. Otherwise the model sees "what stage am I" and adds that the sources don't mention the user's stage, redundant next to the verbatim recall. The saved/displayed message stays exactly as typed, and a missing `general_question` falls back to the full text; when it's personal-only, steps 3–11 below (`_answer_via_retrieval` in `conversations.py`) are skipped entirely — no external search, no OpenSearch, no LLM generation. Classification itself fails safe (LLM error or unparseable output → treated as a general question, so a classifier failure only ever costs a wasted call, never wrongly skips a search that was needed).
3. `src/nlp` calls the NLP microservice (`/extract`) to extract scientific terms and expand them with MeSH synonyms (`extracted_terms` stored on the `Message` row). **This runs exactly once per message**, inside `search_and_embed`, which returns `latest_terms` (the current message's own terms) for `conversations.py` to persist. Do not add a second `_extract_terms_from_message` call in the request path — spell-correction and extraction are each a full scispaCy pipeline pass, and the two used to run twice over identical text
4. **External search** runs in parallel: PubMed (10 results), CrossRef (10 results), Wikipedia (3 results), ClinicalTrials.gov (3 results) queried using NLP-extracted terms (`src/routers/conversation_helper.py`). Wikipedia uses the search API first and picks the most oncology-relevant page from candidates. ClinicalTrials.gov hits the v2 REST API directly (not `pytrials`) and is filtered to `overallStatus=COMPLETED` — this is the *evidence* use case (grounding answers in trial findings); the opt-in *participation* feature (recruiting trials by country/city) is separate and client-side only, see `client/src/components/FindTrialsDialog.tsx`. PubMed and ClinicalTrials share the AND-of-OR-groups boolean query builder (`_build_boolean_term_query`).
5. New external sources are embedded via Ollama (`nomic-embed-text`) and indexed into OpenSearch `sources_index` as **150-word chunks with 40-word overlap**. Each chunk gets `id={base_id}:c{n}`, `source_id={base_id}`, `chunk_index`, `full_text` (original), and `tags` (search terms that retrieved it). Dedup is by `source_id` — if any chunk of a base ID exists, the whole source is skipped. Every chunk in the batch is embedded via `OllamaConnector.embed_texts` (batched, `_EMBED_BATCH_SIZE` per request) and written with a single `dbConnector.bulk_index_to_db` call that refreshes **once** at the end. Do not go back to `embed_text` + `index_to_db(refresh=True)` per chunk here: that was one Ollama round trip and one forced Lucene segment flush per chunk, i.e. dozens of each per chat message. The trailing refresh is what keeps the freshly indexed chunks visible to the retrieval query that runs immediately after.
6. External search results are recorded in `external_search_results` table
7. `src/retrieval/__init__.py:run_retrieval` runs the hybrid search in `search.py:search_sources` on `sources_index`. The dense and lexical halves are issued as **two separate ranked lists in one `msearch`** and combined with **Reciprocal Rank Fusion**; each list is deduped to one chunk per `source_id`, and the fused list is deduped again across sources by DOI. Rather than a fixed top-5, it returns **every fused source whose best chunk clears a cosine-similarity floor (`MIN_COSINE`), capped at `MAX_RESULTS`** — so the count tracks how much the corpus actually covers the query (see the Retrieval section). `run_retrieval` embeds the **natural question** for the dense half while passing the **representative terms** as the lexical query. The gated list is then reordered (never filtered) by a cross-encoder via the NLP service's `/rerank` (`_rerank_sources`; `RERANK_ENABLED=false` turns it off, and any reranker error falls back to RRF order). It runs inline in the caller's worker thread — no separate executor
7a. **Asking about a specific source.** The citation popover's "Ask about this source" button puts the source's id (e.g. `[pmid:123]`) in the message box. `_answer_via_retrieval` (`conversations.py`) detects `[pmid:|doi:|nct:|url:...]` references, fetches those sources **by id** from OpenSearch (`_fetch_referenced_sources`, not from history, so a citation from many turns back still works), puts them first in the generation context (removing any retrieved duplicate) and first in `sources_ids`, and rewrites the question's id tokens to their evidence aliases (`[source1]`, ...) — the model only ever sees aliases. Retrieval searches the question with the id tokens stripped. Items are flagged `focus`, which `_build_prompt` uses to give them a larger evidence cap (`_FOCUS_EVIDENCE_CHARS`, 4000 vs the normal 900 — an abstract's conclusion is usually at the end) and a "SOURCES THE USER ASKED ABOUT" note that lifts the two-source minimum for them; without it, a question about one paper always got the no-evidence fallback. Unknown ids are ignored and the question is left as typed. The button is hidden on read-only shared links.
8. Search analytics recorded in `search_analytics` table
9. `src/classes/ollama_connector.py` builds a prompt with history + context (cited as `[source1]`, `[source2]`, ...) and streams it from the **one** provider `LLM_PROVIDER` selects (`_stream_completion` → `_stream_ollama` / `_stream_groq` / `_stream_gemini`; models from `OLLAMA_GEN_MODEL` / `GROQ_MODEL_NAME` / `GEMINI_MODEL_NAME`). There is **no fallback between providers and no output-token cap** — no `max_tokens`/`num_predict`/`max_output_tokens` is sent, so answers are never cut off and there is no "Continue" flow. A failure before any text raises `LLMUnavailableError` (a `ValueError`, so the routers answer 503); a failure mid-answer keeps the partial text. Every short utility call (query rewrite, personal-question classifier, titles, URL classification) goes through `OllamaConnector.complete`, the non-streaming twin, which returns `None` on an error or empty reply. `src/main.py` refuses to start when `llm_config_errors()` reports an unknown provider or a missing required setting for the chosen one. `messages.truncated` is a legacy column, no longer written or returned.
10. Post-processing replaces `[source1]` aliases with stable base IDs (`pmid:xxx`, `doi:xxx`, `nct:NCTxxx`, `url:<sha1>`) — the `:cN` chunk suffix is stripped before aliases are built
11. Assistant message + source IDs stored in PostgreSQL
12. WebSocket emits staged events throughout (see below)

### WebSocket Stage Events
`loading_conversation` → `saving_user_message` → `fallback_triggered` → `analyzing_recent_messages` → `extracting_search_terms` → `searching_the_internet` (PubMed/CrossRef/Wikipedia/ClinicalTrials run concurrently, so one event covers all four; per-source counts arrive in `found_sources`) → `found_sources` → `embedding_and_indexing_sources` → `sources_indexed` → `retrieving_context` → `building_prompt` → `generating_answer` → `saving_assistant_message` → `done`

**Personal-question fast path** (see Chat Query Flow step 2a) replaces `fallback_triggered` through `generating_answer` with a single `answering_from_profile` event when the message is personal-only — `loading_conversation` → `saving_user_message` → `answering_from_profile` → `saving_assistant_message` → `done`.

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
2. **Reranking only reorders what the cosine gate already kept.** A cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`, hosted in `nlp-service` so torch stays out of the backend image) reorders the gated sources, but retrieval doesn't yet fetch *wider* than `MAX_RESULTS` before reranking — the standard precision upgrade. Doing so means more candidates per cross-encoder call, so measure latency first.
3. **No offline evaluation set.** Boost weights, `RRF_K`, and the question-vs-terms split are all unmeasured heuristics — there is no golden query set, so retrieval changes are argued rather than measured. `search_analytics` now records usable scores (see Retrieval), which is the raw material for building one.
4. **`claims_index` is created + embedded on every startup but never queried.** Either use claims in retrieval or stop maintaining the index.
5. **Chunking is blind fixed-window (150w/40w overlap).** Fine for abstracts (which rarely chunk), but splits trial records and OA full-text mid-sentence; sentence/section-aware chunking would help the longer sources.

**Addressed** (kept here so the reasoning isn't rediscovered): score normalization in `calculate_search_metrics`, additive score blending replaced by RRF, the dense clause now embedding the natural question rather than the joined terms, and cross-source `pmid:`/`doi:` duplicates — all four are described in the Retrieval section. Note the DOI dedup is **preventive**: when it landed, a scan of the live index found 371 sources, 299 distinct DOIs, and *zero* DOIs reachable under more than one `source_id`, so PubMed and CrossRef had not in fact overlapped yet at that corpus size. This is a *retrieval-time* dedup (never hand the LLM the same paper twice) — it doesn't stop the same paper from being *indexed* twice in the first place. That's a separate, later fix: `existing_doi_base_ids` (`db_connector.py`), called from `_embed_and_index_sources` (`conversation_helper.py`) — see the "Data Migrations" section above for the one-off cleanup script (`remove_duplicate_doi_sources.py`) for anything indexed twice before this landed.

### Data Files (`data/`, not in the repository)
Used only by the legacy `src/embedding.py` loader; the live chat flow never reads them.
- `sources_canonical.jsonl` — deduplicated sources (merged by PMID > DOI > URL > title)
- `claims_canonical.jsonl` — structured protocol claims with scoring

### Database Models (`src/db/models.py`)
| Model | Table | Purpose |
|-------|-------|---------|
| `User` | `users` | Auth; has `token_version` (incremented on email change/revert to invalidate old JWTs). `password_hash` is legacy and nullable — nothing reads or writes it since sign-in moved to emailed codes |
| `Conversation` | `conversations` | Soft-deletable chat threads; `forked_from_conversation_id`/`forked_from_message_id` set when created via the "split" message option |
| `Message` | `messages` | Has `sources_ids` (JSON) and `extracted_terms` (JSON) |
| `MessageFeedback` | `message_feedback` | Per-user thumbs up/down (`vote` +1/-1) on an assistant message, unique on `(message_id, user_id)` |
| `Token` | `tokens` | Unified table for sign-in codes, account-deletion, and email-change/revert tokens — see `src/db/repositories/tokens.py` |
| `LoginAttempt` | `login_attempts` | **Legacy.** The old password-login lockout; nothing writes it any more and `auth_cleanup` drains it |
| `RateLimitEntry` | `rate_limit_entries` | Rate limiting for register (per-IP, 10/h) and sign-in codes (per-email 5/h, per-IP 30/h) |
| `SearchAnalytic` | `search_analytics` | Per-message search metrics |
| `ExternalSearchResult` | `external_search_results` | Records PubMed/CrossRef/Wikipedia/ClinicalTrials fetches |
| `UrlClassificationJob` | `url_classification_jobs` | Queue of URLs pending cancer-relevance classification |
| `WaitlistEntry` | `waitlist_entries` | **Legacy, unused.** The registration cap and waitlist were removed; the model stays only so it matches the database (dropping it would make Alembic autogenerate propose deleting the table and its rows). Same for `Token.waitlist_entry_id` |

### Key Environment Variables (`.env`)
`example.env` is the source of truth — every variable, with a comment and a safe placeholder. The non-obvious ones:
- `ENV` — **required**; `src/main.py` refuses to start without it. Anything other than `production` makes token-issuing endpoints return the raw token in the response (for E2E automation), so a real deployment must set `ENV=production`.
- `JWT_SECRET` — required, ≥ 32 characters (checked at import in `src/auth/security.py`). The algorithm is hardcoded to HS256.
- `GROQ_MODEL_NAME` — do **not** wrap in quotes. `openai/gpt-oss-120b` is a reasoning model whose hidden reasoning adds latency; short utility calls pass `reasoning_effort="low"` for that reason (see `OllamaConnector.complete`).
- `LLM_PROVIDER` — `ollama` (default), `groq` or `gemini`; the only provider used for every LLM call. Production sets `groq`. Required per provider: `OLLAMA_GEN_MODEL` (ollama), `GROQ_API_KEY` + `GROQ_MODEL_NAME` (groq), `GEMINI_API_KEY` (gemini; `GEMINI_MODEL_NAME` defaults to `gemini-2.5-flash`).
- `OLLAMA_GEN_MODEL` — local chat model (e.g. `llama3.1:8b`) for `LLM_PROVIDER=ollama`. Expect weaker citation-rule adherence than `openai/gpt-oss-120b` — the prompts are tuned for it. `tests/conftest.py` forces `LLM_PROVIDER=groq` and this blank so tests never call a real local model.
- `OLLAMA_CONTEXT_ITEMS` — must stay ≥ `MAX_RESULTS` in `search.py` (see Retrieval).
- `FRONTEND_URL` — origin used in every emailed link. **Required in production** (`src/main.py` refuses to start without it); elsewhere it falls back to `http://localhost:5173`.
- `CORS_ORIGINS` — comma-separated; `*` refuses to start in production.
- `ADMIN_DIGEST_EMAILS` — comma-separated recipients for admin digests; unset = those emails are skipped.
- `NINJA_EMAIL` — the admin principal (see "Ninja account" below); signs in with a code sent to this address, so it must be a real inbox. Unset = no admin login. `NINJA_PASSWORD` is no longer read.
- `BREVO_API_KEY` — outbound email. Outside production nothing is sent; emails are only logged. In production every sign-in depends on it (and on the arq worker that sends the code).
- `RERANK_ENABLED` — `false` skips the cross-encoder rerank without a redeploy.
- `DEV_EMAIL_SHORTCUTS` — local dev only (`dev_email_shortcuts()` in `src/utils/utils.py`). `/auth/register/` and `/auth/request-code/` also return the sign-in code as `dev_code`, and the code screen shows it, so no inbox is needed. Deliberately a separate opt-in rather than implied by non-production: a code in the response is a login for that account, so on staging it would let anyone sign in as anyone. `tests/conftest.py` forces it off; the E2E suite needs it on (`e2e/helpers.ts`). `src/main.py` refuses to start with it set in production, and `dev_email_shortcuts()` ignores it there regardless.

### Auth
JWT tokens (HS256) accepted via `Authorization: Bearer <token>` header or `access_token` cookie. Dependency: `Depends(get_current_user)` in `src/deps/auth.py`.
- **Passwordless sign-in**: there are no passwords. `POST /auth/register/` (first/last name + email) creates the account unverified and emails a 6-digit code; `POST /auth/request-code/` emails a code to an existing account; `POST /auth/verify-code/` checks it and sets the session cookie (and marks the account verified — entering a code sent to the address is the proof the old verification link gave). Re-registering an address that never entered its code updates the name and sends a new code, so an abandoned sign-up can't lock the address out. Frontend: `CodeStep` + `CodeInput` (6 boxes, paste/autofill across all of them, auto-submit on the sixth digit), used by both `LoginForm` and `RegistrationForm`.
- **Code security** (`src/db/repositories/tokens.py`): 10-minute TTL, single use, a new code replaces the address's previous one, and each code dies after `LOGIN_CODE_MAX_ATTEMPTS` (5) guesses — counted by an atomic `UPDATE ... WHERE use_count < max` *before* the comparison, so parallel guesses can't each get a free try. Codes are keyed by `target_email` (the ninja's code has no `user_id`). Stored as an **HMAC keyed with `JWT_SECRET`**, never plain SHA-256: a 6-digit code's SHA-256 is reversible by trying all million values. The code must never be logged — which is why it's kept out of the email **subject** (`email_brevo.py` logs subjects, in production too) and `send_login_code_email` doesn't log it in dev.
- **JWT revocation**: tokens carry a `tv` (token version) claim. `User.token_version` is incremented on email change and revert; tokens with a mismatched `tv` are rejected with 401.
- **Rate limiting** (all via `RateLimitEntry`): register is per-IP (10/h); sign-in codes are per-email (5/h, shared by register and request-code, and counted for unknown addresses too so a 429 can't reveal which addresses exist) and per-IP (30/h). Outside production, loopback (`127.0.0.1`/`::1`) is exempt so repeated local E2E runs don't lock themselves out (`_rate_limits_apply`).
- **Emails are case-insensitive**: every auth request model uses `LowercaseEmail` (`src/utils/email_normalize.py`), and `create_user`/`get_user_by_email` lowercase too, so `users.email` is always stored lowercase (migration `lowercase_user_emails_001` converted existing rows). This also matters for rate limiting: the per-email code limit is keyed by the submitted email, so case variants must not each get their own budget.
- **No account enumeration at sign-in**: `/auth/request-code/` returns the same `{ok, email}` for known and unknown addresses (an unknown one just gets no email). Known limitation: a known address does a DB write and an enqueue, so the response is slightly slower — the old pbkdf2-sized timing gap is gone, but this one isn't equalised.
- **`/auth/register/` still discloses whether an email is registered** (400 "Email already registered"). Left deliberate: a generic response needs a "someone tried to register" mail flow, loses a genuinely useful error, and `e2e/global-teardown.ts` depends on it.
- **Scheduled deletion at sign-in**: a correct code for an account pending deletion returns 403 `pending_deletion` with a 15-minute `cancel_token` (carrying `tv` and the `rememberMe` choice). `/auth/cancel-delete/` cancels the deletion **and signs the user in** — the code is spent by then, so without that they'd need a second code to reach the account they just rescued.
- **Stale throttling rows** are pruned every 6h by `src/jobs/auth_cleanup.py`. `rate_limit_entries` is keyed by attacker-supplied values (any submitted email, any client IP), so it has no natural bound. The sweep never deletes a row whose block is still in the future.
- **WebSocket Origin**: CORSMiddleware does not cover WS handshakes, so `post_message_ws` checks `Origin` against `CORS_ORIGINS` itself. A *missing* Origin is allowed on purpose — browsers always send one, so its absence means a non-browser client with no ambient cookie.
- **`CORS_ORIGINS='*'`** makes `src/main.py` refuse to start in production. Starlette echoes the request Origin when `allow_credentials=True`, so a wildcard lets any site issue authenticated requests with the user's cookie.
- **Client IP**: `_client_ip` in `auth.py` uses the socket peer only. `X-Forwarded-For` is **not** trusted — the backend serves directly on port 8000, so the header is attacker-controlled and honouring it let anyone defeat the per-IP registration limit by rotating a fake value. If a reverse proxy is ever added, re-enable it *only* for requests whose immediate peer is the proxy, and set `MAX_REGISTER_ATTEMPTS` accordingly — otherwise every user shares one rate-limit bucket.
- **No registration cap.** There used to be a `MAX_USERS` cap with a waitlist and admin-sent invite links; all of it was removed, and registration is always open. A leftover `MAX_USERS` in an old `.env` is ignored (tested in `TestRegister`).

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
- `rerank(question, documents)` → `POST /rerank` — cross-encoder relevance scores; returns `None` on failure so retrieval keeps RRF order

The spaCy/scispaCy logic lives in `nlp_service/extraction.py` (tested by `nlp_service/test_extraction.py` against the real model); `nlp_service/app.py` is the thin FastAPI shell plus the reranker.
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
  - Email: `src/jobs/email_jobs.py` wraps each `src.utils.email.send_*` sender; `src/routers/auth.py`'s email call sites (sign-in codes, account-deletion request/cancel, email change) enqueue these instead of using FastAPI `BackgroundTasks` (which no router uses anymore). `send_account_deleted_email` is the one sender *not* wrapped here — it's only ever called from `delete_scheduled_user_job`, which already runs inside the worker, so there's nothing to enqueue.
  - URL classification: `classify_url_job` (`src/jobs/url_classification.py`) — LLM-classifies a user-provided URL as cancer-related via the configured LLM and, if so, indexes it. `conversation_helper.py`'s `_enqueue_url_classification` still inserts the `url_classification_jobs` row first (it stays the audit/status record — `status`/`llm_reasoning`/`error`/`processed_at` are genuinely useful persisted) and then immediately enqueues `classify_url_job` for it, so classification runs right away instead of waiting for a poll tick. The job claims its row with `FOR UPDATE SKIP LOCKED` scoped to its own id, so a duplicate enqueue of the same job (e.g. racing the reaper) can't double-process it.
  - Account deletion: `delete_scheduled_user_job` (`src/jobs/account_deletion.py`) — **not a cron sweep**. `/auth/confirm-delete/` enqueues it directly via arq's native deferred-execution support (`src.queue.enqueue(..., _defer_until=deletion_date)`), so it fires once, exactly at the 7-day grace-period deadline, instead of an hourly scan of the whole `users` table finding it later. It re-checks `deletion_scheduled_at` at execution time and no-ops if it's `None` (cancelled) or now points to a later date (cancel-then-reschedule) — the correct job is always whichever one was deferred for the *current* value of that column, so nothing needs to explicitly cancel/abort the stale one in Redis. Enqueued with a deterministic `_job_id` (`job_id_for_user`, `delete-user-{id}`) so re-enqueueing the same schedule is a no-op rather than a duplicate. `reschedule_pending_deletions` runs once on worker startup (`WorkerSettings.on_startup`) and re-enqueues (idempotently, same job id) anyone still showing a `deletion_scheduled_at` — the safety net for a deletion scheduled before this job existed, or a deferred job Redis lost (e.g. restarted without persistence).
- **Local dev**: nothing in `WorkerSettings` runs unless a worker process is actually up — running the backend alone (`uvicorn src.main:app --reload`) does not run cron sweeps, deferred jobs, or process enqueued jobs. Run the worker separately if you need that: `arq src.worker.WorkerSettings`.

### Routers (`src/routers/`)
- `auth.py` — registration, emailed sign-in codes, email change, account deletion
- `conversations.py` — CRUD + WebSocket message handling; includes `POST /conversations/create/`
- `health.py` — health check endpoint
- `ninja.py` — admin-only routes gated by `get_current_ninja_user` (`src/deps/auth.py`); see "Ninja account" below

### Ninja account
A single privileged admin principal that is **not a `users` row** — it exists only while `NINJA_EMAIL` is set (unset = no ninja login). It signs in through the normal code endpoints (`_ninja_email` in `src/routers/auth.py`): the code is emailed to `NINJA_EMAIL`, carries no `user_id`, and has the same attempt and rate limits as everyone's. `/auth/register/` and email change refuse that address. It gets a JWT carrying `is_ninja: true` and the sentinel subject `NINJA_SUBJECT_ID`, always capped at 2 hours regardless of `rememberMe` or the dev-only long-expiry override. `/ninja/*` routes are gated by `get_current_ninja_user` (`src/deps/auth.py`), which checks that claim without a database lookup; the sentinel subject can never match a real user, so a ninja token is rejected by every regular `get_current_user` route.

Ninja can browse every user (`GET /ninja/users/`), open any of their conversations (`GET /ninja/users/{id}/conversations/`, `GET /ninja/conversations/{id}/messages/` — the latter includes previously-hidden ninja exchanges for continuity), and post a message into someone else's conversation (`POST /ninja/conversations/{id}/add_message`). That message runs through the exact same search/retrieval/LLM pipeline as a real user message, but both the question and answer are persisted with `Message.hidden_from_user=True`.

`hidden_from_user` messages are excluded by default from `get_messages_by_conversation_id` and `get_recent_messages` (`src/db/repositories/messeges.py`) — the real user's own endpoints and LLM prompt history never see them. This can't be set from a request body (the client-facing `Message` pydantic model has no such field); it's only ever set by `_process_post_message`'s `hidden_from_user` parameter, which only the ninja router passes as `True`.

### Conversation Ordering
Conversations are sorted by `max(message.created_at)` across all roles (see `get_conversations_list_by_user_id` in `src/db/repositories/conversations.py`). `Conversation.updated_at` is **not** bumped when messages are added — do not rely on it for recency ordering.

### OpenSearch — TLS is production-only
`docker-compose.yml` runs OpenSearch for local development with its security plugin disabled (`DISABLE_SECURITY_PLUGIN=true`): plain HTTP on `127.0.0.1:9200`, no admin password, no certificates, so a fresh clone needs no certificate step. `docker-compose.prod.yml` is layered on top in production (every `docker compose` call in `scripts/deploy.sh` passes both files via `COMPOSE_FILES`) and restores the security plugin, TLS on the HTTP and transport layers, the HTTPS healthcheck and dashboards, and HTTPS + the pinned CA for the backend/worker containers. The merged production config is identical to the pre-split single file apart from three explicit `...=false` flags that equal the image defaults.
- `db_connector.py` follows the scheme of `OPENSEARCH_URL`: `http://` gets a plain client (no TLS, no auth, no password needed); `https://` gets TLS + admin auth as below.
- `src/main.py` **refuses to start in production unless `OPENSEARCH_URL` is `https://`**, so TLS can't be dropped by deploying without the prod file.
- Never put TLS-only settings back into `docker-compose.yml`, and never run production compose commands without `-f docker-compose.prod.yml`.

### OpenSearch — Production SSL
Preferred: set `OPENSEARCH_CA_CERT` to a CA cert generated by `scripts/generate_opensearch_certs.sh` (a self-signed root CA + a node cert covering `opensearch-node1`/`localhost`, mounted into the OpenSearch container via `docker-compose.prod.yml`; the script still adds a SAN for the removed `opensearch-node2`, which is harmless). When set, `src/retrieval/db_connector.py` verifies TLS against that specific CA (`verify_certs=True`, real hostname checking) instead of disabling verification — this is what actually closes the "TLS certificate not verified" gap rather than just silencing the warning. Each environment (local dev, prod) generates and keeps its own CA; the private key (`root-ca-key.pem`) must never be committed (it's gitignored under `certs/`).

Fallback (only when `OPENSEARCH_CA_CERT` is unset): `verify_certs=False` alone is insufficient in production (newer urllib3 still validates), so `db_connector.py` explicitly builds an `ssl.CERT_NONE` context when `is_prod() and not verify_certs`, logging a warning. Do not remove this fallback — it exists for environments that haven't yet been migrated to the CA-pinning setup above.

### Migrations — Idempotency Pattern
New migrations that create tables or indexes must use raw SQL with `IF NOT EXISTS` via `op.execute()`, not `op.create_table()` / `op.create_index()`. This avoids `DuplicateTable` errors when revision IDs change between deploys. See `add_bug_reports_table_001.py` as the canonical example.

### Axiom
Initialised in `src/main.py` and `nlp_service/app.py` via `_init_axiom_logging()` — an `AxiomHandler` is attached to the root logger, forwarding standard Python `logging` calls at INFO+ to the Axiom dataset named by `AXIOM_DATASET`, authenticated via `AXIOM_TOKEN_WRITE`. Both env vars must be set for logging to activate; init is skipped silently (no error) if either is missing. Log records carry no explicit environment tag — the logger `name` field (e.g. `src.main`, `nlp_service.app`) is the only built-in way to distinguish sources when querying.

Querying (not just ingesting) uses a **separate** token, `AXIOM_TOKEN_READ` — Axiom scopes tokens per-action, and the ingest token above does not (and should not) also carry query access. Only `src/jobs/admin_digest.py`'s daily digest queries Axiom (`apl_query`, log volume by level + top errors over the last 24h); it degrades gracefully (logs and returns `None`) if `AXIOM_TOKEN_READ`/`AXIOM_DATASET` are unset or the query fails, rather than blocking the digest from sending.

### Deploy Script (`scripts/deploy.sh`)
One-time host setup (firewall, nginx + certbot, Ollama, OpenSearch certs, production `.env`) lives in `docs/server-runbook.html`; keep it in sync with this script (see Code Review Workflow step 6).
- Checks disk free ≥ 10GB (`MIN_FREE_DISK_GB`) before building; runs `docker system prune -a` and re-checks if low. **Never add `--volumes`** — PostgreSQL (`cancerbot_pgdata`) and OpenSearch (`os-data1`) data live in named volumes, and a prune deletes any volume whose container is stopped at that moment (e.g. after a failed deploy)
- Builds with `--pull` so the base image is refreshed when upstream publishes OS patches (e.g. curl CVEs); intermediate layers still cache when the base digest is unchanged
- Scans built images with Trivy (`HIGH`/`CRITICAL`, ignore-unfixed); aborts deploy on findings
- Skips `alembic upgrade heads` if `alembic current` already shows `(head)` — avoids 4 unnecessary Docker container spawns per deploy
- Runs seeds (non-fatal): `seed_wikipedia_tags.py` then `backfill_chunks.py` (scrolls the entire sources index and migrates every doc without a `source_id` field to the chunked schema; idempotent), then `backfill_source_metadata.py` (re-fetches pub_year/pub_types/evidence_level from PubMed for pmid sources missing them; idempotent), then `backfill_conversation_titles.py` (regenerates conversation titles still stuck on the naive first-message-prefix; idempotent)
- Installs `nginx.conf` into `/etc/nginx/sites-available/cancerbot`, replacing its `__PROJECT_DIR__` placeholder with the checkout's path (so the web root follows wherever the repo lives — it was hardcoded to the old Oracle server's `/home/ubuntu`), then tests and reloads nginx. `scripts/setup-nginx.sh` installs the same file the same way
- Prints git commit hash in the success summary
- **Self re-exec after `git pull`**: the script hashes itself before and after the pull; if `deploy.sh` changed, it re-execs from `$SCRIPT_DIR/deploy.sh` (capped at one re-exec via `DEPLOY_REEXEC_COUNT`) instead of continuing on bash's stale in-memory copy of the old script for the rest of the run. Without this, any step *added to deploy.sh itself* in the commit being pulled would silently never run on the very deploy that introduces it — this bit `backfill_conversation_titles.py`'s first deploy. `DEPLOY_LOG_FILE_OVERRIDE` and `DEPLOY_PREV_GIT_HEAD_OVERRIDE` carry the log file and the true pre-deploy commit (for rollback) across the re-exec.
