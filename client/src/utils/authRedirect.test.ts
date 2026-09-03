import { describe, it, expect } from 'vitest'
import { isPendingDeletionResponse, loginPathForAuthFailure } from './authRedirect'

function makeResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status })
}

describe('isPendingDeletionResponse', () => {
  it('is true for a 401 with the pending-deletion detail', async () => {
    const res = makeResponse(401, { detail: 'Account pending deletion' })
    expect(await isPendingDeletionResponse(res)).toBe(true)
  })

  it('is false for a 401 with a different detail', async () => {
    const res = makeResponse(401, { detail: 'Invalid or expired token' })
    expect(await isPendingDeletionResponse(res)).toBe(false)
  })

  it('is false for a non-401 status even with the same detail', async () => {
    const res = makeResponse(403, { detail: 'Account pending deletion' })
    expect(await isPendingDeletionResponse(res)).toBe(false)
  })

  it('is false when the body is not valid JSON', async () => {
    const res = new Response('not json', { status: 401 })
    expect(await isPendingDeletionResponse(res)).toBe(false)
  })
})

describe('loginPathForAuthFailure', () => {
  it('adds the reason param when pending deletion', () => {
    expect(loginPathForAuthFailure(true)).toBe('/login?reason=pending_deletion')
  })

  it('is a plain login path otherwise', () => {
    expect(loginPathForAuthFailure(false)).toBe('/login')
  })
})
