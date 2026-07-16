# CancerBot

A Retrieval-Augmented Generation (RAG) chatbot for cancer-related medical information. Answers are grounded in a curated corpus of medical claims and source documents, with citations traced back to PubMed articles and structured protocol claims.

## Architecture

- **FastAPI** — REST + WebSocket API (port 8000)
- **React + Vite** — frontend (port 5173)
- **Ollama** — local LLM for embedding and text generation (port 11434)
- **OpenSearch** — hybrid BM25 + KNN vector search (port 9200)
- **PostgreSQL** — users, conversations, messages (port 5432)

## Prerequisites

- Python 3.13
- Node.js 18+
- [Ollama](https://ollama.com) installed natively (**not** via Docker — required for Metal/GPU acceleration on Mac)
- Docker + Docker Compose

## Setup

### 1. Environment

```bash
cp example.env .env
# Fill in: OPENSEARCH_INITIAL_ADMIN_PASSWORD, POSTGRES_PASSWORD, JWT_SECRET
```

Generate a JWT secret:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Infrastructure (OpenSearch + PostgreSQL)

```bash
docker compose up -d
```

### 3. Ollama (GPU-accelerated on Mac)

```bash
# Install natively — Docker cannot access Metal GPU
brew install ollama
ollama serve &

ollama pull nomic-embed-text
ollama pull llama3.1:8b
```

Verify GPU is active:

```bash
ollama run llama3.1:8b "hi"
# In another terminal:
ollama ps  # PROCESSOR column should show "100% GPU"
```

### 4. Database migrations

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

alembic upgrade head
```

### 5. Backend

```bash
source .venv/bin/activate
uvicorn src.main:app --reload
```

### 6. Frontend

```bash
cd client
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

## Environment Variables

| Variable                            | Description                                              |
| ----------------------------------- | -------------------------------------------------------- |
| `OPENSEARCH_INITIAL_ADMIN_PASSWORD` | OpenSearch admin password                                |
| `OPENSEARCH_URL`                    | OpenSearch URL (default: `https://localhost:9200`)       |
| `OLLAMA_URL`                        | Ollama URL (default: `http://localhost:11434`)           |
| `EMBED_MODEL_NAME`                  | Embedding model (default: `nomic-embed-text`)            |
| `GEN_MODEL_NAME`                    | Generation model (default: `llama3.1:8b`)                |
| `POSTGRES_URL`                      | PostgreSQL connection string                             |
| `POSTGRES_PASSWORD`                 | PostgreSQL password                                      |
| `JWT_SECRET`                        | Secret key for JWT signing (required)                    |
| `ENV`                               | `development` or `production`                            |
| `PROMPT_MAX_HISTORY`                | Number of conversation turns sent to LLM (default: `12`) |
| `OLLAMA_NUM_CTX`                    | LLM context window size (default: `2048`)                |
| `OLLAMA_NUM_PREDICT`                | Max tokens to generate (default: `384`)                  |
| `OLLAMA_CONTEXT_ITEMS`              | Number of evidence chunks sent to LLM (default: `8`)     |
| `OLLAMA_EVIDENCE_CHARS`             | Max characters per evidence chunk (default: `1200`)      |

## Data Pipeline

To ingest and index new sources:

```bash
# Embed and index into OpenSearch
python -m src.embedding
```

Abstracts (PubMed, CrossRef, Wikipedia) are fetched live per-query during the
chat flow — there is no separate offline enrichment step.

Canonical data files live in `data/`:

- `sources_canonical.jsonl` — deduplicated source documents
- `claims_canonical.jsonl` — structured protocol claims
