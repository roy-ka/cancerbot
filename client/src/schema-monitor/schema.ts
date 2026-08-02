// Runtime API schema monitor — pure logic (no React, no DOM side effects).
//
// Learns the shape of each endpoint's JSON responses over the first N samples,
// then flags drift: missing required fields, changed types, and new unknown
// fields. Kept framework-free so it's trivially unit-testable.

export const LEARN_THRESHOLD = 20
export const CONFIDENCE_THRESHOLD = 0.95
export const STORAGE_KEY = 'schema-monitor:v1'
const MAX_DEPTH = 6

export interface FieldStat {
  /** number of learned samples in which this field was present */
  seen: number
  /** observed JSON type -> count (e.g. {"string": 18, "null": 2}) */
  types: Record<string, number>
}

export interface EndpointSchema {
  /** total learned samples for the endpoint — the confidence denominator */
  sampleCount: number
  /** dot-path -> stats (e.g. "conversation.id", "messages[].role") */
  fields: Record<string, FieldStat>
}

export type SchemaStore = Record<string, EndpointSchema>

export type ViolationKind = 'missing_required' | 'type_changed' | 'unknown_field'

export interface Violation {
  endpoint: string
  kind: ViolationKind
  path: string
  detail: string
}

/** JSON type name of a value. Arrays are "array", null is its own "null". */
export function jsonType(value: unknown): string {
  if (value === null) return 'null'
  if (Array.isArray(value)) return 'array'
  return typeof value // "object" | "string" | "number" | "boolean"
}

/**
 * Flatten a JSON body into { dotPath: jsonType }. Objects recurse by key;
 * arrays record the field as "array" and recurse their first element under a
 * `[]` segment (so `messages[].role` is learned). Depth-capped to stay cheap.
 */
export function flattenFields(body: unknown): Record<string, string> {
  const out: Record<string, string> = {}
  const walk = (value: unknown, prefix: string, depth: number): void => {
    if (depth > MAX_DEPTH) return
    if (Array.isArray(value)) {
      if (value.length > 0) walk(value[0], `${prefix}[]`, depth + 1)
      return
    }
    if (value && typeof value === 'object') {
      for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
        const path = prefix ? `${prefix}.${key}` : key
        out[path] = jsonType(child)
        if (child && typeof child === 'object') walk(child, path, depth + 1)
      }
    }
  }
  walk(body, '', 0)
  return out
}

export function newEndpointSchema(): EndpointSchema {
  return { sampleCount: 0, fields: {} }
}

/** Fold one response into the endpoint's schema (mutates and returns it). */
export function learnSchema(schema: EndpointSchema, body: unknown): EndpointSchema {
  schema.sampleCount += 1
  for (const [path, type] of Object.entries(flattenFields(body))) {
    const stat = (schema.fields[path] ??= { seen: 0, types: {} })
    stat.seen += 1
    stat.types[type] = (stat.types[type] ?? 0) + 1
  }
  return schema
}

/** Concrete (non-null) types a field has been seen with. */
function concreteTypes(stat: FieldStat): string[] {
  return Object.keys(stat.types).filter((t) => t !== 'null')
}

/**
 * Validate a response against a learned schema. Three checks:
 *  1. required field missing — field present in >= CONFIDENCE_THRESHOLD of samples but absent now
 *  2. type changed — a concrete type never seen for this field before
 *  3. unknown field — a path the schema has never seen (drift)
 */
export function validate(schema: EndpointSchema, body: unknown, endpoint: string): Violation[] {
  const violations: Violation[] = []
  const present = flattenFields(body)
  const presentPaths = new Set(Object.keys(present))

  // 1. required fields that vanished
  for (const [path, stat] of Object.entries(schema.fields)) {
    if (schema.sampleCount === 0) continue
    const confidence = stat.seen / schema.sampleCount
    if (confidence >= CONFIDENCE_THRESHOLD && !presentPaths.has(path)) {
      violations.push({
        endpoint,
        kind: 'missing_required',
        path,
        detail: `required field missing (present in ${(confidence * 100).toFixed(0)}% of learned samples)`,
      })
    }
  }

  // 2 & 3. per field present in this response
  for (const [path, type] of Object.entries(present)) {
    const stat = schema.fields[path]
    if (!stat) {
      violations.push({
        endpoint,
        kind: 'unknown_field',
        path,
        detail: `unknown field not seen while learning (type=${type})`,
      })
      continue
    }
    if (type !== 'null') {
      const known = concreteTypes(stat)
      if (known.length > 0 && !known.includes(type)) {
        violations.push({
          endpoint,
          kind: 'type_changed',
          path,
          detail: `type changed: expected ${known.join('|')}, got ${type}`,
        })
      }
    }
  }

  return violations
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * Stable per-endpoint key: METHOD + path with volatile segments templated out.
 * Without this, path params (UUIDs, numeric ids) would make every request a
 * distinct "endpoint" and no schema would ever reach LEARN_THRESHOLD samples.
 */
export function normalizeEndpoint(method: string, url: string): string {
  const base = typeof window !== 'undefined' ? window.location.origin : 'http://localhost'
  let pathname: string
  try {
    pathname = new URL(url, base).pathname
  } catch {
    pathname = url.split('?')[0]
  }
  const normalized = pathname
    .split('/')
    .map((seg) => (UUID_RE.test(seg) || /^\d+$/.test(seg) ? ':id' : seg))
    .join('/')
  return `${method.toUpperCase()} ${normalized}`
}

export function loadStore(): SchemaStore {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as SchemaStore) : {}
  } catch {
    return {}
  }
}

export function saveStore(store: SchemaStore): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store))
  } catch {
    /* localStorage full or unavailable — monitoring must never throw */
  }
}
