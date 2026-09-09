import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { Message } from '../types'
import { openInGoogleTranslate, openConversationInGoogleTranslate } from './googleTranslate'

function message(overrides: Partial<Message> = {}): Message {
  return {
    id: 'm1',
    content: 'Hello',
    role: 'user',
    timestamp: '2026-09-06T12:00:00Z',
    sources: [],
    ...overrides,
  }
}

describe('openInGoogleTranslate', () => {
  let openSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    openSpy = vi.fn()
    vi.stubGlobal('window', { open: openSpy })
    vi.stubGlobal('navigator', { language: 'en-US' })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('opens a translate.google.com URL with the text encoded', () => {
    openInGoogleTranslate('What is cancer?')
    expect(openSpy).toHaveBeenCalledTimes(1)
    const [url, target, features] = openSpy.mock.calls[0] as [string, string, string]
    expect(url).toContain('https://translate.google.com/')
    expect(url).toContain(encodeURIComponent('What is cancer?'))
    expect(target).toBe('_blank')
    expect(features).toBe('noopener,noreferrer')
  })

  it('strips citation tokens before translating', () => {
    openInGoogleTranslate('CLL is a lymphoma [pmid:12345][source2].')
    const [url] = openSpy.mock.calls[0] as [string]
    expect(url).not.toContain('pmid')
    expect(url).not.toContain('source2')
    expect(url).toContain(encodeURIComponent('CLL is a lymphoma .'))
  })
})

describe('openConversationInGoogleTranslate', () => {
  let openSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    openSpy = vi.fn()
    vi.stubGlobal('window', { open: openSpy })
    vi.stubGlobal('navigator', { language: 'en-US' })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('joins every message with its speaker label, in order', () => {
    openConversationInGoogleTranslate([
      message({ role: 'user', content: 'What is cancer?' }),
      message({ role: 'assistant', content: 'Cancer is...' }),
    ])
    const [url] = openSpy.mock.calls[0] as [string]
    const decoded = decodeURIComponent(url)
    expect(decoded.indexOf('You: What is cancer?')).toBeLessThan(
      decoded.indexOf('CancerBot: Cancer is...'),
    )
  })

  it('strips citation tokens from every message', () => {
    openConversationInGoogleTranslate([
      message({ role: 'assistant', content: 'Evidence says so [pmid:1].' }),
    ])
    const [url] = openSpy.mock.calls[0] as [string]
    expect(url).not.toContain('pmid')
  })

  it('handles an empty conversation without throwing', () => {
    expect(() => openConversationInGoogleTranslate([])).not.toThrow()
    expect(openSpy).toHaveBeenCalledTimes(1)
  })
})
