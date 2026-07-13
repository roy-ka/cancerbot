# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CancerBot is a Retrieval-Augmented Generation (RAG) chatbot for cancer-related medical information. It uses a hybrid search approach (BM25 + KNN vector search) over a corpus of medical sources and claims in OpenSearch, with Groq (cloud LLM) for generation (OpenAI as fallback) and Ollama for embeddings only. On every user message, the system also performs live external search (PubMed, CrossRef, Wikipedia), embeds the results, and indexes them into OpenSearch before retrieval.

## Dependencies

Every library or service added to the codebase must be declared in the appropriate file before use:
- Python packages → `requirements.txt`
- Frontend packages → `client/package.json` (via `npm install <pkg>`)
- Docker services → `docker-compose.yml`

Never import a package or depend on a service that is not listed in the relevant file.

## Environment Variables

Every new `.env` entry must also be added to `example.env`:
- Include the actual value if it is **not secret** (e.g. `FRONTEND_URL=https://cancer-bot.com`, `ENV=production`)
- Use a placeholder for secrets (e.g. `SENDGRID_API_KEY=your-sendgrid-api-key`, `JWT_SECRET=your-jwt-secret`)

After committing, explicitly remind the user to update their `.env` with the new variable.

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

## Commands

### Backend API
```bash
# Install dependencies
pip install -r requirements.txt

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
python -m src.enricher       # Fetch missing abstracts from PubMed/CrossRef/Wikipedia
python -m src.embedding      # Embed documents into OpenSearch via Ollama
```

### Backup / Restore
```bash
python scripts/backup_db.py   # Dump PostgreSQL to file (optionally upload to S3)
python scripts/restore_db.py  # Restore from a dump file
bash scripts/daily_backup.sh  # Cron-friendly wrapper for backup
```

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

### New Conversation Flow
Frontend first calls `POST /conversations/create/` (lightweight DB-only, returns `{id, title}`), then immediately opens a WebSocket to `/conversations/{id}/add_message/ws`. This ensures stage events fire from the very start instead of the UI freezing on `loading_conversation`.

### Chat Query Flow
1. User message arrives via WebSocket (`/conversations/{id}/add_message/ws`) or HTTP POST (`/conversations/{id}/add_message`)
2. User message is saved to PostgreSQL
3. `src/nlp` calls the NLP microservice (`/extract`) to extract scientific terms and expand them with MeSH synonyms (`extracted_terms` stored on the `Message` row)
4. **External search** runs in parallel: PubMed (4 results), CrossRef (4 results), Wikipedia (3 results) queried using NLP-extracted terms (`src/routers/conversation_helper.py`). Wikipedia uses the search API first and picks the most oncology-relevant page from candidates.
5. New external sources are embedded via Ollama (`nomic-embed-text`) and indexed into OpenSearch `sources_index` as **150-word chunks with 40-word overlap**. Each chunk gets `id={base_id}:c{n}`, `source_id={base_id}`, `chunk_index`, `full_text` (original), and `tags` (search terms that retrieved it). Dedup is by `source_id` — if any chunk of a base ID exists, the whole source is skipped.
6. External search results are recorded in `external_search_results` table
7. `src/retrieval/__init__.py:run_retrieval` embeds the query and runs hybrid BM25 + KNN search on `sources_index` with `collapse` on `source_id` — returns top 5 unique sources (1 best chunk per source)
8. Search analytics recorded in `search_analytics` table
9. `src/classes/ollama_connector.py` builds a prompt with history + context (cited as `[R1]`, `[R2]`, ...) and calls Groq chat completions (`GROQ_MODEL_NAME`). On `groq.GroqError`, falls back to OpenAI (`OPENAI_FALLBACK_MODEL`).
10. Post-processing replaces `[R1]` aliases with stable IDs (`pmid:xxx:c0`, `doi:xxx:c0`, `url:<sha1>:c0`)
11. Assistant message + source IDs stored in PostgreSQL
12. WebSocket emits staged events throughout (see below)

### WebSocket Stage Events
`loading_conversation` → `saving_user_message` → `fallback_triggered` → `analyzing_recent_messages` → `extracting_search_terms` → `searching_pubmed` / `searching_crossref` / `searching_wikipedia` → `found_sources` → `embedding_and_indexing_sources` → `sources_indexed` → `retrieving_context` → `building_prompt` → `generating_answer` → `saving_assistant_message` → `done`

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
- `pmid`, `doi`, `title`, `url`, `source_type`, `abstract_source` — provenance fields

### Retrieval
`src/retrieval/search.py:search_sources` runs a hybrid query against `sources_index` only:
- KNN vector clause (boost ×2, k=5)
- BM25 match on `content_for_embedding` (boost ×1) and `title` (boost ×1.5)
- `collapse` on `source_id` (keyword) — ensures at most 1 chunk per source in the top 5 results
- Works with Lucene-engine KNN (OpenSearch 3); requires `source_id` to be a `keyword` field

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
| `ExternalSearchResult` | `external_search_results` | Records PubMed/CrossRef/Wikipedia fetches |

### Key Environment Variables (`.env`)
```
# OpenSearch
OPENSEARCH_URL=https://localhost:9200
OPENSEARCH_INITIAL_ADMIN_PASSWORD=...

# Ollama (embeddings only)
OLLAMA_URL=http://localhost:11434       # used in dev
OLLAMA_URL_PROD=http://...             # used in prod (is_prod() check)
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

# Email (SendGrid) — required for password reset
SENDGRID_API_KEY=...
EMAIL_FROM=noreply@example.com
EMAIL_FROM_NAME=CancerBot

# Backups — optional S3 upload
BACKUP_S3_BUCKET=...

# OpenAI (fallback LLM when Groq is unavailable)
OPENAI_API_KEY=...
OPENAI_FALLBACK_MODEL=gpt-4o-mini

# Optional integrations
UNPAYWALL_EMAIL=
```

### Auth
JWT tokens (HS256) accepted via `Authorization: Bearer <token>` header or `access_token` cookie. Dependency: `Depends(get_current_user)` in `src/deps/auth.py`.
- **JWT revocation**: tokens carry a `tv` (token version) claim. `User.token_version` is incremented on password reset; tokens with a mismatched `tv` are rejected with 401.
- **Rate limiting**: login uses `LoginAttempt` (5 failures → 15 min lockout); register uses per-IP limit (10/h); forgot-password uses per-email limit (5/h) — both via `RateLimitEntry`.
- **Password reset**: time-limited codes via SendGrid email.

### NLP
`src/nlp/__init__.py` is a thin HTTP client that calls the **NLP microservice** (`nlp_service/`) over HTTP. The microservice runs scispaCy (`en_core_sci_sm`) + SpellChecker in a separate Docker container (`nlp-service`, port 8100). URL configured via `NLP_SERVICE_URL` env var (default `http://localhost:8100`).
- `extract_terms(text)` → `POST /extract` — entity extraction + abbreviation expansion + MeSH synonym lookup (`nlp_service/synonyms.py`); returns merged term list
- `correct_spelling(text)` → `POST /spelling/correct` — spell correction with protected medical terms
- `load_models()` — no-op; logs the service URL at startup

### Routers (`src/routers/`)
- `auth.py` — registration, login, password reset
- `conversations.py` — CRUD + WebSocket message handling; includes `POST /conversations/create/`
- `health.py` — health check endpoint

### Conversation Ordering
Conversations are sorted by `max(message.created_at)` across all roles (see `get_conversations_list_by_user_id` in `src/db/repositories/conversations.py`). `Conversation.updated_at` is **not** bumped when messages are added — do not rely on it for recency ordering.

### OpenSearch — Production SSL
In production with self-signed certs, `verify_certs=False` alone is insufficient (newer urllib3 still validates). `src/retrieval/db_connector.py` explicitly builds an `ssl.CERT_NONE` context when `is_prod() and not verify_certs`. Do not remove this — it is required for the prod OpenSearch cluster.

### Migrations — Idempotency Pattern
New migrations that create tables or indexes must use raw SQL with `IF NOT EXISTS` via `op.execute()`, not `op.create_table()` / `op.create_index()`. This avoids `DuplicateTable` errors when revision IDs change between deploys. See `add_bug_reports_table_001.py` as the canonical example.

### Sentry
Initialised in `src/main.py` with `enable_logs=True` — standard Python `logging` calls at INFO+ are forwarded to Sentry Logs (Explore → Logs). `LoggingIntegration(event_level=logging.ERROR)` creates Sentry Issues for ERROR+. No custom bridge handler is needed. The nginx CSP must include `https://*.ingest.de.sentry.io https://*.ingest.sentry.io` in `connect-src` (already set in `nginx.conf`).

### Deploy Script (`scripts/deploy.sh`)
- Checks disk free ≥ 100GB before building; runs `docker system prune` and re-checks if low
- Builds with `--pull` so the base image is refreshed when upstream publishes OS patches (e.g. curl CVEs); intermediate layers still cache when the base digest is unchanged
- Scans built images with Trivy (`HIGH`/`CRITICAL`, ignore-unfixed); aborts deploy on findings
- Skips `alembic upgrade heads` if `alembic current` already shows `(head)` — avoids 4 unnecessary Docker container spawns per deploy
- Runs seeds (non-fatal): `seed_wikipedia_tags.py` then `backfill_chunks.py` (migrates old single-doc OpenSearch entries to chunked schema, idempotent)
- Prints git commit hash in the success summary
