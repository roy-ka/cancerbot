# CancerBot TODO

## Pending
- [ ] **Mobile support** — responsive UI for the React frontend
- [ ] **Mailing** — transactional emails beyond password reset (e.g. conversation summaries, weekly digests)
- [ ] **Delete user** — account deletion endpoint: remove user row, cascade conversations/messages, revoke tokens
- [ ] **Unify oncology keyword sets** — `_ONCOLOGY_KEYWORDS` in `conversation_helper.py` and `CANCER_KEYWORDS` in the same file serve overlapping purposes; consolidate (note: `"oncol"` partial match is only in `_ONCOLOGY_KEYWORDS`)
- [ ] **Wikipedia HTTP connection pooling** — `_wiki_search` creates a new `httpx` connection per call; reuse a `httpx.Client` within `_fetch()` to avoid per-term TLS handshake overhead
- [ ] **Token budget check + fallback** — before calling Groq, check remaining token quota; if exhausted, fall back to TBD (different model / cached response / graceful error)
- [ ] **Skip Wikipedia search when already indexed** — when indexing a Wikipedia page into OpenSearch, store the source term as a tag (e.g. `wikipedia:term:<term>`) alongside the existing `"wikipedia"` tag; before calling the Wikipedia API for a term, query OpenSearch for that tag and skip the external fetch if a hit exists
