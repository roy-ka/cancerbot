# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CancerBot is a Retrieval-Augmented Generation (RAG) chatbot for cancer-related medical information. It uses a hybrid search approach (BM25 + KNN vector search) over a corpus of medical claims and source documents, with a local LLM (Ollama) for generation.

## Code Review Workflow

**Before committing changes, always:**

1. **Review** - Examine all changed code for correctness
2. **Fix Security** - Check for vulnerabilities (SQL injection, XSS, command injection, etc.)
3. **Optimize** - Improve performance, remove unnecessary code, simplify logic
4. **Verify** - Test changes work as intended (TypeScript/Python compilation, runtime behavior)

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
# Starts: OpenSearch (9200), Dashboards (5601), Ollama (11434), PostgreSQL (5432), NLP Service (8011)
# The FastAPI backend and Vite frontend are run separately (not in Docker)
```

### Data Pipeline
```bash
python -m src.enricher       # Fetch missing abstracts from PubMed/CrossRef/Wikipedia
python -m src.embedding      # Embed documents into OpenSearch via Ollama
```

## Architecture

### Services and Ports
| Component | Entry Point | Port |
|-----------|-------------|------|
| FastAPI backend | `src/main.py` | 8000 |
| React frontend | `client/src/main.tsx` | 5173 |
| NLP microservice | `nlp_service/app.py` | 8011 |
| OpenSearch | Docker | 9200 |
| PostgreSQL | Docker | 5432 |
| Ollama | Docker | 11434 |

### Chat Query Flow
1. User message arrives via WebSocket (`/conversations/{id}/add_message/ws`)
2. `src/retrieval/router.py` classifies intent: **concept** (definition/mechanism) vs **intervention** (treatment/diet)
3. Query is embedded via Ollama (`nomic-embed-text`)
4. `src/retrieval/search.py` runs hybrid search on two OpenSearch indices: claims and sources
5. `src/retrieval/hybrid.py` ranks results — concept queries prioritize sources; intervention queries prioritize claims
6. `src/classes/ollama_connector.py` builds a prompt with history + context (cited as `[R1]`, `[R2]`, ...) and calls Ollama generate
7. Post-processing replaces `[R1]` aliases with stable IDs (`pmid:xxx`, `doi:xxx`, `Cxx`)
8. Message + linked claim/source IDs stored in PostgreSQL
9. WebSocket emits staged events: `loading`, `saving_user_message`, `retrieving_context`, `generating_answer`, `done`

### OpenSearch Indices
- `v1.5_en_nomic-embed-text_index` — sources (768-dim KNN + BM25 on `content_for_embedding`, `title`)
- `v1.5_claims_nomic-embed-text_index` — claims (same structure, BM25 on `protocol_claim_en`, `tags`, `risk_flags`)

### Data Files (`data/`)
- `sources_canonical.jsonl` — deduplicated sources (merged by PMID > DOI > URL > title)
- `sources_for_embedding.jsonl` — derived from canonical, includes `content_for_embedding` field
- `claims_canonical.jsonl` — structured protocol claims with scoring

### Key Environment Variables (`.env`)
```
OPENSEARCH_URL=https://localhost:9200
OPENSEARCH_INITIAL_ADMIN_PASSWORD=...
OLLAMA_URL=http://localhost:11434
EMBED_MODEL_NAME=nomic-embed-text
GEN_MODEL_NAME=llama3.1:8b
POSTGRES_URL=postgresql+asyncpg://...
NLP_URL=http://127.0.0.1:8011
JWT_SECRET=...
OLLAMA_NUM_CTX=1536
OLLAMA_NUM_PREDICT=256
OLLAMA_CONTEXT_ITEMS=6        # Number of context chunks sent to LLM
OLLAMA_EVIDENCE_CHARS=900     # Max chars per evidence chunk
PROMPT_MAX_HISTORY=12         # Conversation turns included in prompt
```

### Auth
JWT tokens (HS256) accepted via `Authorization: Bearer <token>` header or `access_token` cookie. Dependency: `Depends(get_current_user)` in `src/auth/`.

### NLP Service
Standalone FastAPI service using scispacy (`en_core_sci_sm`). Provides:
- `POST /extract` — entity extraction + abbreviation detection
- `POST /spelling/correct` — spell correction with protected medical terms
- Abbreviation cache refreshed from PostgreSQL every 60s
