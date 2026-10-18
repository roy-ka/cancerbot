/**
 * API-level E2E tests for the citation pipeline.
 *
 * These tests bypass the frontend and call the FastAPI backend directly, so
 * they catch citation bugs even when the UI is not running. They:
 *   1. Log in fresh against the API (not through the browser)
 *   2. Create a conversation and POST a cancer question
 *   3. Assert the assistant message has non-empty sources with clean IDs
 */
import { test, expect, request as playwrightRequest } from '@playwright/test'
import { signInViaApi } from '../helpers'

const E2E_API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000'
const E2E_EMAIL = process.env.E2E_EMAIL ?? 'e2e-test@example.com'

// Disable the browser storageState — this suite talks directly to the API,
// not to the frontend, so the browser session is irrelevant.
test.use({ storageState: { cookies: [], origins: [] } })

type ApiSource = {
  id: string
  name: string
  source_type: string
  url?: string
  phase?: string | null
  status?: string | null
}
type ApiMessage = { id: string; role: string; content: string; sources: ApiSource[] | null }

test.describe('Citation pipeline (API)', () => {
  test('add_message returns non-empty sources for a cancer question', async () => {
    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })

    // Sign in — API sets the access_token cookie on its domain
    await signInViaApi(api, E2E_EMAIL)

    // Create a conversation
    const create = await api.post('/conversations/create/', {
      data: { title: 'E2E Citation Test' },
    })
    expect(create.status()).toBe(201)
    const { id: conversationId } = await create.json()

    // Send a specific cancer question; wait up to 110 s for the full LLM + search pipeline
    const msg = await api.post(`/conversations/${conversationId}/add_message`, {
      data: { content: 'What are the standard treatments for glioblastoma multiforme?' },
      timeout: 110_000,
    })
    expect(msg.ok(), `add_message failed: ${msg.status()} ${await msg.text()}`).toBeTruthy()

    const body = await msg.json()
    const assistant = (body.messages as ApiMessage[])?.find(m => m.role === 'assistant')

    expect(assistant, 'assistant message should be present').toBeTruthy()
    expect(Array.isArray(assistant!.sources), 'sources should be an array').toBe(true)
    expect(assistant!.sources!.length, 'at least one source expected').toBeGreaterThan(0)

    // Verify every source ID has the :cN chunk suffix stripped
    for (const src of assistant!.sources!) {
      expect(src.id, `source '${src.id}' must not contain a :cN chunk suffix`).not.toMatch(/:c\d+$/)
    }

    await api.dispose()
  })

  test('source IDs stored in DB match what add_message returns', async () => {
    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })

    await signInViaApi(api, E2E_EMAIL)

    const create = await api.post('/conversations/create/', {
      data: { title: 'E2E ID Consistency Test' },
    })
    const { id: conversationId } = await create.json()

    const msg = await api.post(`/conversations/${conversationId}/add_message`, {
      data: { content: 'Explain EGFR mutations in lung cancer.' },
      timeout: 110_000,
    })
    expect(msg.ok()).toBeTruthy()
    const body = await msg.json()
    const firstResponse = (body.messages as ApiMessage[])?.find(m => m.role === 'assistant')
    const sourceIdsFromCreate = firstResponse?.sources?.map(s => s.id) ?? []

    // Re-fetch the messages via GET — sources should be the same
    const fetch = await api.get(`/conversations/${conversationId}/messages/`)
    expect(fetch.ok()).toBeTruthy()
    const fetched = await fetch.json()
    const assistant = (fetched.messages as ApiMessage[])?.find(m => m.role === 'assistant')

    expect(assistant?.sources).toBeTruthy()
    const sourceIdsFromFetch = (assistant!.sources ?? []).map(s => s.id)

    expect(sourceIdsFromFetch.sort()).toEqual(sourceIdsFromCreate.sort())

    await api.dispose()
  })

  test('clinical-trial sources expose a display name and phase/status shape', async () => {
    // The UI distinguishes trial sources with a "Trial · Phase · Status" badge,
    // fed by the backend surfacing the trial title as `name` and parsing
    // `phase`/`status`. Whether a given query actually retrieves a completed
    // trial isn't guaranteed, so this asserts the *shape* of any trial source
    // that appears and skips if none do — rather than pretending a full-stack
    // trial retrieval is deterministic. A drug-repurposing query is the most
    // trial-heavy prompt available.
    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })

    await signInViaApi(api, E2E_EMAIL)

    const create = await api.post('/conversations/create/', {
      data: { title: 'E2E Trial Source Test' },
    })
    const { id: conversationId } = await create.json()

    const msg = await api.post(`/conversations/${conversationId}/add_message`, {
      data: { content: 'Are there completed clinical trials of mebendazole for glioblastoma?' },
      timeout: 110_000,
    })
    expect(msg.ok(), `add_message failed: ${msg.status()} ${await msg.text()}`).toBeTruthy()

    const body = await msg.json()
    const assistant = (body.messages as ApiMessage[])?.find(m => m.role === 'assistant')
    const trials = (assistant?.sources ?? []).filter(s => s.source_type === 'clinicaltrials')

    test.skip(trials.length === 0, 'no clinical-trial source retrieved for this query run')

    for (const trial of trials) {
      // The display name must be the trial title, not the raw `nct:NCT…` id.
      expect(trial.name, `trial '${trial.id}' name should not be the raw nct id`).not.toMatch(/^nct:/i)
      expect(trial.name.length).toBeGreaterThan(0)
      // phase/status keys must be present (value may be null for a bare registration).
      expect(trial).toHaveProperty('phase')
      expect(trial).toHaveProperty('status')
    }

    await api.dispose()
  })
})
