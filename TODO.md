# CancerBot TODO

## Critical
- [x] **Rate limiting on register and forgot-password** — `/auth/register/` and `/auth/forgot-password/` have no abuse protection; add per-IP or per-email rate limiting consistent with the `LoginAttempt` pattern already used for login
- [x] **JWT token revocation on password change** — tokens are 60,000-minute JWTs with no invalidation list; resetting or changing password should invalidate all existing sessions
- [x] **Token budget check + fallback** — catches `groq.GroqError` and retries with OpenAI (`gpt-4o-mini` by default); both providers failing raises a clear error; controlled by `OPENAI_API_KEY` and `OPENAI_FALLBACK_MODEL`
- [x] **Retry logic for external APIs** — `_retry_get` async helper with exponential backoff (1s → 2s + jitter) retries on 429/5xx and network/timeout errors; used by PubMed and CrossRef; `_wiki_search` has equivalent sync retry; 2 attempts, 8s timeout
- [x] **OpenSearch index cleanup** — sources chunked (150w/40w overlap) with source_id dedup; search deduped to 1 result per source_id; backfill script migrates existing docs using terms from PostgreSQL messages

## High
- [x] **Change password** — authenticated endpoint allowing users to update their password (current password + new password)
- [x] **Delete user** — email-confirmed deletion with a 7-day grace period: request email → confirm with password → scheduled deletion → login blocked/cancellable in the meantime → background sweep cascades and sends the farewell email
- [ ] **Ninja user** — on startup, create a privileged "ninja" user if it doesn't exist; username and password sourced from env vars (e.g. `NINJA_USERNAME`, `NINJA_PASSWORD`)
- [x] **LLM response streaming** — WebSocket infrastructure already exists; stream Groq tokens incrementally instead of buffering the full response, significantly improving perceived latency

## Medium
- [ ] **Conversation title auto-generation** — derive a short title from the first user message (via LLM or heuristic) instead of storing a generic placeholder
- [ ] **Source recency scoring** — boost retrieval score for recently published sources; publication year should influence ranking so newer evidence surfaces above old docs with high BM25/KNN scores
- [ ] **Improve search using tags** — enrich OpenSearch documents with structured tags (source type, disease area, publication year, evidence level) so retrieval can filter/boost by tag alongside BM25+KNN; apply equivalent field-level filters when querying PubMed (MeSH terms, publication type) and CrossRef (subject, type) to narrow external results before embedding
- [ ] **Wikipedia HTTP connection pooling** — `_wiki_search` creates a new `httpx` connection per call; reuse a `httpx.Client` within `_fetch()` to avoid per-term TLS handshake overhead

- [ ] **Split name into first and last** — replace the single `name` field on `User` with `first_name` + `last_name`; update registration, profile, and email templates accordingly

- [ ] **Rate limiting on `/auth/request-delete/`** — no throttle unlike `/auth/forgot-password/`; low severity since it requires an already-authenticated session, but a hijacked session or client bug could spam deletion-confirmation emails indefinitely
- [ ] **Pending-deletion logout has no explanation** — when `get_current_user` rejects a session because deletion was scheduled from another device, the user is silently bounced to `/login` with no message; the "cancel deletion" dialog only appears after resubmitting the login form. Surface this via a query param/toast on the redirect instead
- [ ] **Tokenized links logged to Axiom in non-prod** — `send_password_reset_email` and `send_delete_account_request_email` both log the full link (including the live token) whenever `ENV != production`; Axiom's handler has no environment gating of its own, so a staging deployment with `AXIOM_TOKEN`/`AXIOM_DATASET` set forwards working tokens to a third-party log store. Redact the token from these log lines
- [ ] **Index `deletion_scheduled_at`** — the hourly account-deletion sweep (`src/jobs/account_deletion.py`) does a full sequential scan of `users`; add a partial index (`WHERE deletion_scheduled_at IS NOT NULL`) before the user base grows
- [ ] **Deletion-cancellation email** — `cancel_delete_account` (`src/routers/auth.py`) clears `deletion_scheduled_at` but sends no confirmation email; the request and scheduled-deletion steps both email the user, cancellation should too (new `EMAIL_TEMPLATES` entry + sender in `src/utils/email.py`)

## Bugs
- [x] **Delete conversation not visible** — the delete conversation action is not exposed in the UI; users have no way to delete a conversation from the frontend
- [ ] **Fix sources in prod** — (2026-07-20) something's wrong with sources in production; needs investigation to pin down the actual issue

## Nice to Have
- [ ] **Email change** — authenticated endpoint to update email address with re-verification flow (pairs with Change password)
- [ ] **Conversation export** — allow users to download a conversation as markdown or PDF
- [ ] **Mailing** — transactional emails beyond password reset (e.g. conversation summaries, weekly digests)
- [ ] **Multiple language support** — allow users to query and receive responses in languages other than English; consider UI locale switching, multilingual embeddings, and translated MeSH synonyms

- [ ] **Consolidate token-repository logic** — `password_resets.py`, `email_verification.py`, and `account_deletion.py` each reimplement the same hash/create/verify/consume pattern; extract a shared base so a future fix (e.g. the tz-naive datetime normalization) doesn't need to be applied three times
- [ ] **Make the login `cancel_token` DB-backed** — it's currently a bare stateless JWT, unlike every other token type in the app (all DB-backed and revocable); low risk today (15-min TTL, only issued after correct password entry) but inconsistent with the rest of the codebase's token handling and can't be revoked early short of rotating `JWT_SECRET`
