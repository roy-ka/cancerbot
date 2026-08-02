import { useCallback, useRef, type ReactNode } from 'react'
import { useFetchInterceptor, type InterceptedResponse } from './useFetchInterceptor'
import {
  loadStore,
  saveStore,
  learnSchema,
  validate,
  normalizeEndpoint,
  newEndpointSchema,
  LEARN_THRESHOLD,
  type SchemaStore,
} from './schema'

/**
 * Wrap the app to monitor API responses for schema drift.
 *
 * Dev-only: in a production build this renders children with no fetch patching.
 * Patching window.fetch and cloning/parsing every response is pure overhead for
 * real users, and schema drift is a development/CI concern.
 */
export function SchemaProvider({ children }: { children: ReactNode }) {
  if (!import.meta.env.DEV) return <>{children}</>
  return <SchemaMonitor>{children}</SchemaMonitor>
}

function SchemaMonitor({ children }: { children: ReactNode }) {
  // One store for the component's lifetime, seeded from localStorage.
  const storeRef = useRef<SchemaStore | null>(null)
  if (storeRef.current === null) storeRef.current = loadStore()

  const onResponse = useCallback((r: InterceptedResponse) => {
    // Learn/validate only from successful JSON *objects*: error bodies
    // ({"detail": ...}) and top-level arrays would poison the learned shape.
    if (r.status < 200 || r.status >= 300) return
    if (!r.body || typeof r.body !== 'object' || Array.isArray(r.body)) return

    const store = storeRef.current!
    const key = normalizeEndpoint(r.method, r.url)
    const schema = (store[key] ??= newEndpointSchema())

    if (schema.sampleCount < LEARN_THRESHOLD) {
      learnSchema(schema, r.body)
      if (schema.sampleCount === LEARN_THRESHOLD) {
        console.info(
          `[schema-monitor] learned ${key} (${Object.keys(schema.fields).length} fields, ${schema.sampleCount} samples)`,
        )
      }
    } else {
      const violations = validate(schema, r.body, key)
      if (violations.length > 0) {
        console.warn(`[schema-monitor] ${violations.length} violation(s) on ${key}`, violations)
      }
    }

    saveStore(store)
  }, [])

  useFetchInterceptor(onResponse)
  return <>{children}</>
}
