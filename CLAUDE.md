# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CancerBot is a Retrieval-Augmented Generation (RAG) chatbot for cancer-related medical information. It uses a hybrid search approach (BM25 + KNN vector search) over a corpus of medical sources and claims in OpenSearch, with a local LLM (Ollama) for generation. On every user message, the system also performs live external search (PubMed, CrossRef, Wikipedia), embeds the results, and indexes them into OpenSearch before retrieval.

## Code Review Workflow

**Before committing changes, always:**

1. **Ask** - Ask the user for confirmation before creating any commit
2. **Review** - Examine all changed code for correctness, then improve it (remove dead code, simplify logic, fix style)
3. **Fix Security** - Check for vulnerabilities (SQL injection, XSS, command injection, etc.)
4. **Test** - Run the test suite and confirm it passes before committing
5. **Verify** - Test changes work as intended (TypeScript/Python compilation, runtime behavior)
6. **Push** - After committing, always push to remote (`git push`)

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

### NLP Service
```bash
cd nlp_service
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8011
```

### Full Stack (Docker)
```bash
docker-compose up --build
# Default profile starts: OpenSearch cluster (2 nodes on 9200), Dashboards (5601),
#   Ollama (11434), PostgreSQL (5432), NLP Service (8011)
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
| NLP microservice | `nlp_service/app.py` | 8011 | In Docker |
| OpenSearch node 1 | Docker | 9200/9600 | 2-node cluster |
| OpenSearch node 2 | Docker | — | Same cluster |
| OpenSearch Dashboards | Docker | 5601 | |
| PostgreSQL | Docker | 5432 | |
| Ollama | Docker | 11434 | |

### Chat Query Flow
1. User message arrives via WebSocket (`/conversations/{id}/add_message/ws`) or HTTP POST (`/conversations/{id}/add_message`)
2. User message is saved to PostgreSQL
3. NLP service extracts scientific terms from the user message (`extracted_terms` stored on the `Message` row)
4. **External search** runs in parallel: PubMed (4 results), CrossRef (4 results), Wikipedia (3 results) queried using NLP-extracted terms (`src/routers/conversation_helper.py`)
5. New external sources are embedded via Ollama (`nomic-embed-text`) and indexed into OpenSearch `sources_index`; duplicates are skipped by stable ID
6. External search results are recorded in `external_search_results` table
7. `src/retrieval/__init__.py:run_retrieval` embeds the query and runs hybrid BM25 + KNN search on `sources_index` (top 5 returned)
8. Search analytics recorded in `search_analytics` table
9. `src/classes/ollama_connector.py` builds a prompt with history + context (cited as `[R1]`, `[R2]`, ...) and calls Ollama generate
10. Post-processing replaces `[R1]` aliases with stable IDs (`pmid:xxx`, `doi:xxx`, `url:<sha1>`)
11. Assistant message + source IDs stored in PostgreSQL
12. WebSocket emits staged events throughout (see below)

### WebSocket Stage Events
`loading_conversation` → `saving_user_message` → `fallback_triggered` → `analyzing_recent_messages` → `extracting_search_terms` → `searching_pubmed` / `searching_crossref` / `searching_wikipedia` → `found_sources` → `embedding_and_indexing_sources` → `sources_indexed` → `retrieving_context` → `building_prompt` → `generating_answer` → `saving_assistant_message` → `done`

### OpenSearch Indices
- `v1.5_en_nomic-embed-text_index` — sources (768-dim KNN `cosinesimil` via `hnsw`/`lucene` + BM25 on `content_for_embedding`, `title`)
- `v1.5_claims_nomic-embed-text_index` — claims (same structure; exists but not queried in the main retrieval path)

Indices are auto-created on startup via `dbConnector.ensure_all_indexes()`.

### Retrieval
`src/retrieval/search.py:search_sources` runs a hybrid query against `sources_index` only:
- KNN vector clause (boost ×2, k=5)
- BM25 match on `content_for_embedding` (boost ×1) and `title` (boost ×1.5)

`src/retrieval/router.py:classify_intent` still classifies queries as `concept` vs `intervention` (keyword matching), but this classification is not used in the current retrieval path.

### Intent Classification (`src/retrieval/router.py`)
- **concept** — "what is", "mechanism", "pathway", "how does", etc. → sources-first ordering
- **intervention** — "treatment", "diet", "supplement", "fasting", "metformin", etc. → claims-first ordering
- Currently not wired into the main retrieval path; available for future use.

### Data Files (`data/`)
- `sources_canonical.jsonl` — deduplicated sources (merged by PMID > DOI > URL > title)
- `sources_for_embedding.jsonl` — derived from canonical, includes `content_for_embedding` field
- `claims_canonical.jsonl` — structured protocol claims with scoring

### Database Models (`src/db/models.py`)
| Model | Table | Purpose |
|-------|-------|---------|
| `User` | `users` | Auth |
| `Conversation` | `conversations` | Soft-deletable chat threads |
| `Message` | `messages` | Has `sources_ids` (JSON) and `extracted_terms` (JSON) |
| `PasswordResetCode` | `password_reset_codes` | Time-limited reset tokens |
| `LoginAttempt` | `login_attempts` | Brute-force tracking |
| `SearchAnalytic` | `search_analytics` | Per-message search metrics |
| `ExternalSearchResult` | `external_search_results` | Records PubMed/CrossRef/Wikipedia fetches |

### Key Environment Variables (`.env`)
```
# OpenSearch
OPENSEARCH_URL=https://localhost:9200
OPENSEARCH_INITIAL_ADMIN_PASSWORD=...

# Ollama
OLLAMA_URL=http://localhost:11434       # used in dev
OLLAMA_URL_PROD=http://...             # used in prod (is_prod() check)
EMBED_MODEL_NAME=nomic-embed-text
GEN_MODEL_NAME=llama3.1:8b
OLLAMA_NUM_CTX=1536
OLLAMA_NUM_PREDICT=256
OLLAMA_CONTEXT_ITEMS=6                 # Number of context chunks sent to LLM
OLLAMA_EVIDENCE_CHARS=900              # Max chars per evidence chunk

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
NLP_URL=http://127.0.0.1:8011
PROMPT_MAX_HISTORY=12                  # Conversation turns included in prompt
ENV=development                        # set to 'production' in prod

# Email (SendGrid) — required for password reset
SENDGRID_API_KEY=...
EMAIL_FROM=noreply@example.com
EMAIL_FROM_NAME=CancerBot

# Backups — optional S3 upload
BACKUP_S3_BUCKET=...

# Optional integrations
OPENAI_API_KEY=
UNPAYWALL_EMAIL=
```

### Auth
JWT tokens (HS256) accepted via `Authorization: Bearer <token>` header or `access_token` cookie. Dependency: `Depends(get_current_user)` in `src/deps/auth.py`. Rate-limited login via `LoginAttempt` model. Password reset via time-limited codes (SendGrid email).

### NLP Service (`nlp_service/app.py`)
Standalone FastAPI service using scispacy (`en_core_sci_sm`). Provides:
- `POST /extract` — entity extraction + abbreviation detection + expansion
- `POST /spelling/correct` — spell correction with protected medical terms
- `GET /abbrev/{short}` — abbreviation lookup
- `GET /abbrev/search` — fuzzy abbreviation search
- `POST /abbrev/reload` — reload in-memory cache
- `GET /health` — liveness check

**Note:** PostgreSQL integration is currently **disabled** in the NLP service (`DATABASE_ENABLED = False` in `nlp_service/app.py`). Abbreviation persistence is a no-op; the in-memory cache is populated only from terms discovered in the current session.

### Routers (`src/routers/`)
- `auth.py` — registration, login, password reset
- `conversations.py` — CRUD + WebSocket message handling
- `health.py` — health check endpoint
