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
client. The backend image is built and run twice (backend + url-classifier), so
the scispaCy stack and its model cost hundreds of MB per container for nothing.
For the same reason `src/utils/utils.py` must stay pandas-free — it's imported by
`main.py`, `auth.py` and `db_connector.py`, so a module-level `import pandas`
loads pandas + numpy into every backend and worker process.

## Email Templates

All SendGrid template IDs must be stored in the `EMAIL_TEMPLATES` dict in `src/utils/email.py`. Never hardcode a template ID inline elsewhere in the codebase — always reference it via `EMAIL_TEMPLATES["key"]`.

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

**Port binding**: only the backend (8000) is published on `0.0.0.0`. OpenSearch
(9200/9600), Dashboards (5601), PostgreSQL (5432) and the NLP service (8100) are
bound to `127.0.0.1` in `docker-compose.yml` — they were reachable from any host
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
4. **External search** runs in parallel: PubMed (4 results), CrossRef (4 results), Wikipedia (3 results), ClinicalTrials.gov (3 results) queried using NLP-extracted terms (`src/routers/conversation_helper.py`). Wikipedia uses the search API first and picks the most oncology-relevant page from candidates. ClinicalTrials.gov hits the v2 REST API directly (not `pytrials`) and is filtered to `overallStatus=COMPLETED` — this is the *evidence* use case (grounding answers in trial findings); a separate opt-in *participation* feature (recruiting trials by location) is deferred. PubMed and ClinicalTrials share the AND-of-OR-groups boolean query builder (`_build_boolean_term_query`).
5. New external sources are embedded via Ollama (`nomic-embed-text`) and indexed into OpenSearch `sources_index` as **150-word chunks with 40-word overlap**. Each chunk gets `id={base_id}:c{n}`, `source_id={base_id}`, `chunk_index`, `full_text` (original), and `tags` (search terms that retrieved it). Dedup is by `source_id` — if any chunk of a base ID exists, the whole source is skipped. Every chunk in the batch is embedded via `OllamaConnector.embed_texts` (batched, `_EMBED_BATCH_SIZE` per request) and written with a single `dbConnector.bulk_index_to_db` call that refreshes **once** at the end. Do not go back to `embed_text` + `index_to_db(refresh=True)` per chunk here: that was one Ollama round trip and one forced Lucene segment flush per chunk, i.e. dozens of each per chat message. The trailing refresh is what keeps the freshly indexed chunks visible to the retrieval query that runs immediately after.
6. External search results are recorded in `external_search_results` table
7. `src/retrieval/__init__.py:run_retrieval` embeds the query and runs hybrid BM25 + KNN search on `sources_index` with `collapse` on `source_id` — returns top 5 unique sources (1 best chunk per source)
8. Search analytics recorded in `search_analytics` table
9. `src/classes/ollama_connector.py` builds a prompt with history + context (cited as `[source1]`, `[source2]`, ...) and calls Groq chat completions (`GROQ_MODEL_NAME`). On `groq.GroqError`, falls back to Gemini (`GEMINI_FALLBACK_MODEL`).
10. Post-processing replaces `[source1]` aliases with stable base IDs (`pmid:xxx`, `doi:xxx`, `nct:NCTxxx`, `url:<sha1>`) — the `:cN` chunk suffix is stripped before aliases are built
11. Assistant message + source IDs stored in PostgreSQL
12. WebSocket emits staged events throughout (see below)

### WebSocket Stage Events
`loading_conversation` → `saving_user_message` → `fallback_triggered` → `analyzing_recent_messages` → `extracting_search_terms` → `searching_pubmed` / `searching_crossref` / `searching_wikipedia` / `searching_clinicaltrials` → `found_sources` → `embedding_and_indexing_sources` → `sources_indexed` → `retrieving_context` → `building_prompt` → `generating_answer` → `saving_assistant_message` → `done`

### OpenSearch Indices
- `v1.5_en_nomic-embed-text_index` — sources (768-dim KNN `cosinesimil` via `hnsw`/`lucene` + BM25 on `content_for_embedding`, `title`)
- `v1.5_claims_nomic-embed-text_index` — claims (same structure; exists but not queried in the main retrieval path)

Indices are auto-created on startup via `dbConnector.ensure_all_indexes()`.

**Source document fields (chunked schema):**
- `id` — `{base_id}:c{n}` (e.g. `pmid:12345:c0`) — unique per chunk
- `source_id` — base ID without chunk suffix (e.g. `pmid:12345`) — used for dedup and `collapse`
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
`src/retrieval/search.py:search_sources` runs a hybrid query against `sources_index` only. **Matching and scoring are deliberately separated**:
- `must` — a nested bool holding the actual matching clauses (`minimum_should_match: 1`): KNN vector (boost ×2), BM25 on `content_for_embedding` (×1) and `title` (×1.5)
- `should` — pure boosts that raise a matching doc's score but can never make a doc match on their own: `evidence_level`, `pub_year` recency, `disease_areas` overlap with the query's entity categories
- `filter` — `full_text_word_count >= MIN_FULLTEXT_WORDS`
- `must_not` — `pub_types` in `EXCLUDED_PUB_TYPES` (editorials, comments, errata, retractions)

Keeping boosts out of the top-level `should` matters: with everything flat under one `minimum_should_match: 1`, a doc could qualify on a boost clause alone (e.g. merely being recent) without matching the query at all.

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
- Works with Lucene-engine KNN (OpenSearch 3); requires `source_id` to be a `keyword` field
- **Caveat**: OpenSearch silently drops documents that have no value for the collapse field. Docs indexed by `embedding.py` before the chunked schema was introduced lack `source_id` and are therefore invisible to retrieval until `backfill_chunks.py` migrates them.

**Mapping caveat**: `_ensure_chunk_fields_mapping()` (`db_connector.py`) must not declare `full_text_word_count` — it's already dynamically mapped as `long`, and `put_mapping` is atomic, so declaring it as `integer` makes OpenSearch reject the *entire* request and silently take the other field mappings down with it. Without those, `pub_types`/`disease_areas` fall back to analyzed `text` and exact-match `terms` queries stop working.

### Data Files (`data/`)
- `sources_canonical.jsonl` — deduplicated sources (merged by PMID > DOI > URL > title)
- `sources_for_embedding.jsonl` — derived from canonical, includes `content_for_embedding` field
- `claims_canonical.jsonl` — structured protocol claims with scoring

### Database Models (`src/db/models.py`)
| Model | Table | Purpose |
|-------|-------|---------|
| `User` | `users` | Auth; has `token_version` (incremented on password reset to invalidate old JWTs) |
| `Conversation` | `conversations` | Soft-deletable chat threads |
| `Message` | `messages` | Has `sources_ids` (JSON) and `extracted_terms` (JSON) |
| `PasswordResetCode` | `password_reset_codes` | Time-limited reset tokens |
| `LoginAttempt` | `login_attempts` | Brute-force tracking (login) |
| `RateLimitEntry` | `rate_limit_entries` | Rate limiting for register (per-IP, 10/h) and forgot-password (per-email, 5/h) |
| `SearchAnalytic` | `search_analytics` | Per-message search metrics |
| `ExternalSearchResult` | `external_search_results` | Records PubMed/CrossRef/Wikipedia/ClinicalTrials fetches |
| `UrlClassificationJob` | `url_classification_jobs` | Queue of URLs pending cancer-relevance classification |

### Key Environment Variables (`.env`)
```
# OpenSearch
OPENSEARCH_URL=https://localhost:9200
OPENSEARCH_INITIAL_ADMIN_PASSWORD=...

# Ollama (embeddings only)
OLLAMA_URL=http://localhost:11434       # dev; set to http://ollama:11434 in Docker prod
EMBED_MODEL_NAME=nomic-embed-text
OLLAMA_CONTEXT_ITEMS=6                 # number of context chunks sent to LLM

# NLP microservice
NLP_SERVICE_URL=http://localhost:8100  # http://nlp-service:8100 in Docker prod
OLLAMA_EVIDENCE_CHARS=900              # max chars per evidence chunk

# Groq (text generation)
GROQ_API_KEY=...
GROQ_MODEL_NAME=llama-3.3-70b-versatile  # required — do NOT wrap in quotes
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
- **Client IP**: `_client_ip` in `auth.py` uses the socket peer only. `X-Forwarded-For` is **not** trusted — the backend serves directly on port 8000, so the header is attacker-controlled and honouring it let anyone defeat the per-IP registration limit by rotating a fake value. If a reverse proxy is ever added, re-enable it *only* for requests whose immediate peer is the proxy, and set `MAX_REGISTER_ATTEMPTS` accordingly — otherwise every user shares one rate-limit bucket.

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
Initialised in `src/main.py` and `nlp_service/app.py` via `_init_axiom_logging()` — an `AxiomHandler` is attached to the root logger, forwarding standard Python `logging` calls at INFO+ to the Axiom dataset named by `AXIOM_DATASET`, authenticated via `AXIOM_TOKEN`. Both env vars must be set for logging to activate; init is skipped silently (no error) if either is missing. Log records carry no explicit environment tag — the logger `name` field (e.g. `src.main`, `nlp_service.app`) is the only built-in way to distinguish sources when querying.

### Deploy Script (`scripts/deploy.sh`)
- Checks disk free ≥ 100GB before building; runs `docker system prune` and re-checks if low
- Builds with `--pull` so the base image is refreshed when upstream publishes OS patches (e.g. curl CVEs); intermediate layers still cache when the base digest is unchanged
- Scans built images with Trivy (`HIGH`/`CRITICAL`, ignore-unfixed); aborts deploy on findings
- Skips `alembic upgrade heads` if `alembic current` already shows `(head)` — avoids 4 unnecessary Docker container spawns per deploy
- Runs seeds (non-fatal): `seed_wikipedia_tags.py` then `backfill_chunks.py` (scrolls the entire sources index and migrates every doc without a `source_id` field to the chunked schema; idempotent), then `backfill_source_metadata.py` (re-fetches pub_year/pub_types/evidence_level from PubMed for pmid sources missing them; idempotent), then `backfill_conversation_titles.py` (regenerates conversation titles still stuck on the naive first-message-prefix; idempotent)
- Prints git commit hash in the success summary
- **Self re-exec after `git pull`**: the script hashes itself before and after the pull; if `deploy.sh` changed, it re-execs from `$SCRIPT_DIR/deploy.sh` (capped at one re-exec via `DEPLOY_REEXEC_COUNT`) instead of continuing on bash's stale in-memory copy of the old script for the rest of the run. Without this, any step *added to deploy.sh itself* in the commit being pulled would silently never run on the very deploy that introduces it — this bit `backfill_conversation_titles.py`'s first deploy. `DEPLOY_LOG_FILE_OVERRIDE` and `DEPLOY_PREV_GIT_HEAD_OVERRIDE` carry the log file and the true pre-deploy commit (for rollback) across the re-exec.
