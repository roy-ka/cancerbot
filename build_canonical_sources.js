#!/usr/bin/env node
/**
 * build_canonical_sources.js
 *
 * Inputs you said you have:
 *   data/merged_rag_sources_deduped.jsonl
 *   data/rag_sources_resolved.jsonl
 *   data/rag_sources_unresolved_resolved.jsonl
 *   data/protocol_claims_with_pubmed_and_wikipedia.json  (used to link claim_ids to sources, optional)
 *
 * Outputs:
 *   data/sources_canonical.jsonl            // merged + deduped sources
 *   data/sources_for_embedding.jsonl        // same sources with content_for_embedding
 *   data/claims_canonical.jsonl             // optional: claims as their own index
 *
 * Node 18+. No npm deps.
 */

const fs = require('fs')
const crypto = require('crypto')
const path = require('path')

const INPUT_SOURCES = [
  'data/merged_rag_sources_deduped.jsonl',
  'data/rag_sources_resolved.jsonl',
  'data/rag_sources_unresolved_resolved.jsonl',
]

const INPUT_CLAIMS_JSON = 'data/protocol_claims_with_pubmed_and_wikipedia.json'

const OUT_CANON = 'data/sources_canonical.jsonl'
const OUT_EMBED = 'data/sources_for_embedding.jsonl'
const OUT_CLAIMS = 'data/claims_canonical.jsonl'

function normSpace(s) {
  return (s || '').toString().replace(/\s+/g, ' ').trim()
}

function canonUrl(u) {
  if (!u) return ''
  let url = normSpace(u).replace(/^http:\/\//i, 'https://')
  url = url.replace(/[)\].,;]+$/g, '')
  // normalize PubMed urls
  const m = url.match(/pubmed\.ncbi\.nlm\.nih\.gov\/(\d+)/i)
  if (m) return `https://pubmed.ncbi.nlm.nih.gov/${m[1]}/`
  return url
}

function sha1(s) {
  return crypto.createHash('sha1').update(s, 'utf8').digest('hex')
}

function docKey(d) {
  const pmid = String(d.pmid || '').replace(/\D/g, '')
  const doi = normSpace(d.doi || '').toLowerCase()
  const url = canonUrl(d.url || d.link || '')
  const title = normSpace(d.title || '').toLowerCase()

  if (pmid) return { type: 'pmid', key: pmid }
  if (doi) return { type: 'doi', key: doi }
  if (url) return { type: 'url', key: url.toLowerCase() }
  if (title) return { type: 'title', key: sha1(title) }
  return { type: 'anon', key: sha1(JSON.stringify(d)) }
}

// Prefer “best” source_type on collisions
const SOURCE_PRIORITY = {
  pubmed: 100,
  semanticscholar: 80,
  openalex: 70,
  crossref: 60,
  wikipedia: 20,
  other_site: 10,
  unresolved_citation: 0,
  resolved_external: 50,
}

function sourcePriority(d) {
  const t = (d.source_type || '').toLowerCase()
  return SOURCE_PRIORITY[t] ?? 40
}

// Merge fields: keep existing if it's already good; fill blanks from new
function mergeInto(base, incoming) {
  // union tags
  base.tags = Array.from(
    new Set([...(base.tags || []), ...(incoming.tags || [])])
  )

  // union claim_ids if present
  base.claim_ids = Array.from(
    new Set([...(base.claim_ids || []), ...(incoming.claim_ids || [])])
  )

  // fill missing metadata
  const FIELDS = [
    'title',
    'abstract',
    'pmid',
    'doi',
    'url',
    'journal',
    'year',
    'authors',
    'pub_types',
    'evidence_score_0_5',
    'evidence_strength',
    'chatbot_data_quality_score_0_100',
    'search_query_used',
    'match_similarity',
    'low_confidence_match',
  ]

  for (const f of FIELDS) {
    const b = base[f]
    const inc = incoming[f]

    const bEmpty =
      b == null ||
      b === '' ||
      (Array.isArray(b) && b.length === 0) ||
      (typeof b === 'number' && b === 0 && f === 'evidence_score_0_5') ||
      (typeof b === 'string' && b === 'unknown' && f === 'evidence_strength')

    if (
      bEmpty &&
      inc != null &&
      inc !== '' &&
      (!Array.isArray(inc) || inc.length)
    ) {
      base[f] = inc
    }
  }

  // ensure canonical url normalization
  if (base.url) base.url = canonUrl(base.url)

  return base
}

function readJsonl(fp) {
  const txt = fs.readFileSync(fp, 'utf8')
  const lines = txt
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
  return lines.map((l) => JSON.parse(l))
}

function writeJsonl(fp, arr) {
  fs.writeFileSync(
    fp,
    arr.map((o) => JSON.stringify(o)).join('\n') + '\n',
    'utf8'
  )
}

function safeInt(x) {
  const n = Number(x)
  return Number.isFinite(n) ? n : null
}

function makeEmbeddingContent(d) {
  const title = normSpace(d.title)
  const abs = normSpace(d.abstract)
  if (title && abs) return `${title}\n\n${abs}`
  if (title) return title
  return ''
}

function isWikipedia(d) {
  return (d.source_type || '').toLowerCase() === 'wikipedia'
}

function main() {
  // 1) Load all sources
  let all = []
  for (const fp of INPUT_SOURCES) {
    if (!fs.existsSync(fp)) {
      console.error(`Missing file: ${fp}`)
      process.exit(1)
    }
    const items = readJsonl(fp)
    all.push(...items)
  }

  // normalize fields
  all = all.map((d) => {
    const out = { ...d }
    out.url = canonUrl(out.url || out.link || '')
    if (!out.tags) out.tags = []
    if (!out.claim_ids) out.claim_ids = []
    if (out.year != null) out.year = safeInt(out.year)
    return out
  })

  // 2) Merge + dedupe
  const map = new Map()
  for (const d of all) {
    const k = docKey(d)
    const keyStr = `${k.type}:${k.key}`

    if (!map.has(keyStr)) {
      map.set(keyStr, d)
      continue
    }

    // On collision: choose higher-priority base, then merge in the other
    const cur = map.get(keyStr)
    const curP = sourcePriority(cur)
    const newP = sourcePriority(d)

    if (newP > curP) {
      // swap, but keep data from old too
      const base = d
      mergeInto(base, cur)
      map.set(keyStr, base)
    } else {
      mergeInto(cur, d)
      map.set(keyStr, cur)
    }
  }

  const canonical = Array.from(map.values())

  // 3) Add a stable id
  for (const d of canonical) {
    const k = docKey(d)
    d.id = `src_${k.type}_${k.key}`
    d.url = canonUrl(d.url || '')
    // Wikipedia as context-only
    if (isWikipedia(d) && !d.tags.includes('secondary_context'))
      d.tags.push('secondary_context')
  }

  // 4) OPTIONAL: also export claims as a separate index
  if (fs.existsSync(INPUT_CLAIMS_JSON)) {
    const claims = JSON.parse(fs.readFileSync(INPUT_CLAIMS_JSON, 'utf8'))
    const claimRows = claims.map((c) => ({
      claim_id: c.claim_id,
      protocol_claim_en: c.protocol_claim_en,
      evidence_score_0_5: c.evidence_score_0_5,
      chatbot_data_quality_score_0_100: c.chatbot_data_quality_score_0_100,
      risk_flags: c.risk_flags || [],
      wikipedia_sources: c.wikipedia_sources || [],
      key_evidence: c.key_evidence || [],
      tags: ['claim'],
    }))
    writeJsonl(OUT_CLAIMS, claimRows)
    console.log(`Wrote claims index: ${OUT_CLAIMS} (${claimRows.length})`)
  } else {
    console.log(
      `Claims file not found, skipping claims index: ${INPUT_CLAIMS_JSON}`
    )
  }

  // 5) Build embedding-ready file
  const forEmbed = canonical
    .map((d) => ({
      ...d,
      content_for_embedding: makeEmbeddingContent(d),
    }))
    .filter((d) => d.content_for_embedding.length >= 20) // skip extremely thin records

  writeJsonl(OUT_CANON, canonical)
  writeJsonl(OUT_EMBED, forEmbed)

  console.log(`Merged inputs: ${INPUT_SOURCES.join(', ')}`)
  console.log(`Canonical sources: ${canonical.length} -> ${OUT_CANON}`)
  console.log(`Embedding-ready sources: ${forEmbed.length} -> ${OUT_EMBED}`)
}

main()
