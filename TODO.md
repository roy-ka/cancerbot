# CancerBot TODO

## Critical
- [x] **Rate limiting on register and forgot-password** — `/auth/register/` and `/auth/forgot-password/` have no abuse protection; add per-IP or per-email rate limiting consistent with the `LoginAttempt` pattern already used for login
- [x] **JWT token revocation on password change** — tokens are 60,000-minute JWTs with no invalidation list; resetting or changing password should invalidate all existing sessions
- [x] **Token budget check + fallback** — catches `groq.GroqError` and retries with OpenAI (`gpt-4o-mini` by default); both providers failing raises a clear error; controlled by `OPENAI_API_KEY` and `OPENAI_FALLBACK_MODEL`
- [x] **Retry logic for external APIs** — `_retry_get` async helper with exponential backoff (1s → 2s + jitter) retries on 429/5xx and network/timeout errors; used by PubMed and CrossRef; `_wiki_search` has equivalent sync retry; 2 attempts, 8s timeout
- [x] **OpenSearch index cleanup** — sources chunked (150w/40w overlap) with source_id dedup; search deduped to 1 result per source_id; backfill script migrates existing docs using terms from PostgreSQL messages

## High
- [x] **Change password** — authenticated endpoint allowing users to update their password (current password + new password)
- [ ] **Delete user** — account deletion endpoint: remove user row, cascade conversations/messages, revoke tokens
- [ ] **Ninja user** — on startup, create a privileged "ninja" user if it doesn't exist; username and password sourced from env vars (e.g. `NINJA_USERNAME`, `NINJA_PASSWORD`)
- [ ] **LLM response streaming** — WebSocket infrastructure already exists; stream Groq tokens incrementally instead of buffering the full response, significantly improving perceived latency

## Medium
- [ ] **Conversation title auto-generation** — derive a short title from the first user message (via LLM or heuristic) instead of storing a generic placeholder
- [ ] **Source recency scoring** — boost retrieval score for recently published sources; publication year should influence ranking so newer evidence surfaces above old docs with high BM25/KNN scores
- [ ] **Improve search using tags** — enrich OpenSearch documents with structured tags (source type, disease area, publication year, evidence level) so retrieval can filter/boost by tag alongside BM25+KNN; apply equivalent field-level filters when querying PubMed (MeSH terms, publication type) and CrossRef (subject, type) to narrow external results before embedding
- [ ] **Wikipedia HTTP connection pooling** — `_wiki_search` creates a new `httpx` connection per call; reuse a `httpx.Client` within `_fetch()` to avoid per-term TLS handshake overhead

- [ ] **Split name into first and last** — replace the single `name` field on `User` with `first_name` + `last_name`; update registration, profile, and email templates accordingly

## Nice to Have
- [ ] **Email change** — authenticated endpoint to update email address with re-verification flow (pairs with Change password)
- [ ] **Conversation export** — allow users to download a conversation as markdown or PDF
- [ ] **Mailing** — transactional emails beyond password reset (e.g. conversation summaries, weekly digests)
- [ ] **Multiple language support** — allow users to query and receive responses in languages other than English; consider UI locale switching, multilingual embeddings, and translated MeSH synonyms
