# RAG Data Artifacts (Canonical vs Build Outputs)

This folder contains source documents and protocol claims used for a RAG chatbot.

## Canonical files (keep, version, and treat as truth)

### `sources_canonical.jsonl`

Single merged + deduped sources library.

- Dedup priority: PMID > DOI > canonical URL > normalized title
- Metadata preference: pubmed > semanticscholar > openalex > crossref > wikipedia > other
- Includes scoring fields such as `evidence_score_0_5` and `chatbot_data_quality_score_0_100`

### `sources_for_embedding.jsonl`

Derived from `sources_canonical.jsonl` for vector indexing.

- Adds `content_for_embedding` (usually `title + "\n\n" + abstract`)
- Filters out records too thin to embed
- This is what you embed into the vector DB

### `claims_canonical.jsonl` (optional but recommended)

Structured protocol claims index.

- One row per claim
- Includes scores/risk flags and source links
- Useful to keep chatbot answers consistent and reduce hallucinated “protocol steps”

## Build artifacts (do not use at runtime; can be deleted or archived)

These are intermediate outputs from resolver steps and earlier merges:

- `rag_sources_resolved.jsonl`
- `rag_sources_unresolved_resolved.jsonl`
- `merged_rag_sourcesdeduped.jsonl`
- `protocol_claims_with_pubmed_and_wikipedia.json` (superseded by `claims_canonical.jsonl`)

Recommended: move build artifacts under `data/raw/` or delete after confirming the canonical outputs exist.

## Runtime usage

1. Embed `sources_for_embedding.jsonl` into your vector store.
2. At query time:
   - Retrieve top-K chunks via vector search.
   - Use `sources_canonical.jsonl` for citations/metadata display.
   - Optionally retrieve related claims from `claims_canonical.jsonl` to structure answers.

## Guardrails for quality

Suggested filters:

- Prefer `source_type=pubmed`
- Prefer `evidence_score_0_5 >= 3`
- Prefer `chatbot_data_quality_score_0_100 >= 60`
- Wikipedia should be treated as context-only, not as clinical evidence.

# pipeline diagram:

RAW INPUTS
|
|-- protocol_claims_with_pubmed_and_wikipedia.json (claims + linked refs)
|
|-- merged_rag_sourcesdeduped.jsonl (older merged sources)
|-- rag_sources_resolved.jsonl (PubMed resolver output)
|-- rag_sources_unresolved_resolved.jsonl (OpenAlex/S2/Crossref resolver output)
v

BUILD STEP: merge + dedupe + prioritize metadata

- dedupe key: PMID > DOI > canonical URL > normalized title
- prefer metadata source: pubmed > semanticscholar > openalex > crossref > wikipedia > other
- normalize schema + tags
  v

CANONICAL OUTPUTS (the only “truth” files)
|
|-- sources_canonical.jsonl ✅ ground truth sources library
| (all sources merged + deduped + scored + normalized)
|
|-- claims_canonical.jsonl ✅ ground truth claims library (optional but recommended)
| (structured claims + scores + links)
|
v

DERIVED OUTPUT (for vector DB ingestion)
|
|-- sources_for_embedding.jsonl ✅ embed-this file
(adds content_for_embedding, filters thin records)

RUNTIME (chatbot)

- retrieve from vector DB built from sources_for_embedding.jsonl
- cite/metadata from sources_canonical.jsonl
- optionally ground responses in claims_canonical.jsonl
