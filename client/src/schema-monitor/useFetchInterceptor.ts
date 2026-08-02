import { useEffect, useRef } from 'react'

export interface InterceptedResponse {
  url: string
  method: string
  status: number
  /** parsed JSON body, or undefined when the response wasn't JSON / failed to parse */
  body: unknown
}

/**
 * Monkey-patch window.fetch for the lifetime of the mounted component.
 *
 * Every response is clone()d (before anyone reads it), parsed as JSON, and
 * handed to `callback` — the original response is always returned untouched, so
 * the app's own `.json()`/`.text()` still works. Parsing is fire-and-forget so
 * it never delays the caller, and any failure is swallowed: monitoring must
 * never break a real request.
 *
 * Only responses with a JSON content-type are parsed; SSE/streaming, empty, and
 * non-JSON responses pass straight through.
 */
export function useFetchInterceptor(callback: (r: InterceptedResponse) => void): void {
  const callbackRef = useRef(callback)
  useEffect(() => {
    callbackRef.current = callback
  }, [callback])

  useEffect(() => {
    const original = window.fetch

    window.fetch = async (...args: Parameters<typeof fetch>): Promise<Response> => {
      const response = await original(...args)
      try {
        const [input, init] = args
        const url = input instanceof Request ? input.url : String(input)
        const method = (
          init?.method || (input instanceof Request ? input.method : 'GET')
        ).toUpperCase()
        const contentType = response.headers.get('content-type') || ''
        if (contentType.includes('application/json')) {
          response
            .clone()
            .json()
            .then((body) => callbackRef.current({ url, method, status: response.status, body }))
            .catch(() => {
              /* unparseable body — ignore */
            })
        }
      } catch {
        /* never let interception interfere with the fetch */
      }
      return response
    }

    return () => {
      window.fetch = original
    }
  }, [])
}
