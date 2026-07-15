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

const E2E_API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000'
const E2E_EMAIL = process.env.E2E_EMAIL ?? 'e2e-test@example.com'
const E2E_PASSWORD = process.env.E2E_PASSWORD ?? 'E2eTest123!'

// Disable the browser storageState — this suite talks directly to the API,
// not to the frontend, so the browser session is irrelevant.
test.use({ storageState: { cookies: [], origins: [] } })

type ApiSource = { id: string; name: string; source_type: string; url?: string }
type ApiMessage = { id: string; role: string; content: string; sources: ApiSource[] | null }

test.describe('Citation pipeline (API)', () => {
  test('add_message returns non-empty sources for a cancer question', async () => {
    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })

    // Login — API sets the access_token cookie on its domain
    const login = await api.post('/auth/login/', {
      data: { email: E2E_EMAIL, password: E2E_PASSWORD },
    })
    expect(login.ok(), `login failed: ${login.status()} ${await login.text()}`).toBeTruthy()

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

    const login = await api.post('/auth/login/', {
      data: { email: E2E_EMAIL, password: E2E_PASSWORD },
    })
    expect(login.ok()).toBeTruthy()

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
})
