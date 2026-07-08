# CancerBot TODO

## Pending
- [ ] **Ninja user** — on startup, create a privileged "ninja" user if it doesn't exist; username and password sourced from env vars (e.g. `NINJA_USERNAME`, `NINJA_PASSWORD`)
- [x] **Mobile support** — verify on device; login + chat layout fixed, sidebar toggle implemented
- [x] **Password reset email** — token-based link (60 min TTL, 5 uses max), SendGrid dynamic template `d-89a37afdde454f699046dda66cfca385` with `name` + `link`; `/reset-password` accepts `{token, new_password}`; migration `add_password_reset_use_count_001`
- [ ] **Mailing** — transactional emails beyond password reset (e.g. conversation summaries, weekly digests)
- [ ] **Delete user** — account deletion endpoint: remove user row, cascade conversations/messages, revoke tokens
- [ ] **Change password** — authenticated endpoint allowing users to update their password (current password + new password)
- [x] **Unify oncology keyword sets** — removed `_ONCOLOGY_KEYWORDS`, `_pick_oncology_title` now uses `CANCER_KEYWORDS`; added `"onco"` prefix to `CANCER_KEYWORDS`
- [ ] **Wikipedia HTTP connection pooling** — `_wiki_search` creates a new `httpx` connection per call; reuse a `httpx.Client` within `_fetch()` to avoid per-term TLS handshake overhead
- [ ] **Token budget check + fallback** — before calling Groq, check remaining token quota; if exhausted, fall back to TBD (different model / cached response / graceful error)
- [ ] **Multiple language support** — allow users to query and receive responses in languages other than English; consider UI locale switching, multilingual embeddings, and translated MeSH synonyms
- [x] **Skip Wikipedia search when already indexed** — `dbConnector.existing_tags()` queries by `tags.keyword` aggregation; `_search_wikipedia_sources` checks at start of fetch and skips terms whose `wikipedia:term:<term>` tag is already indexed; tag is written on first index
- [ ] **Improve search using tags** — enrich OpenSearch documents with structured tags (source type, disease area, publication year, evidence level) so retrieval can filter/boost by tag alongside BM25+KNN; apply equivalent field-level filters when querying PubMed (MeSH terms, publication type) and CrossRef (subject, type) to narrow external results before embedding
