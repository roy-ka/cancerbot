import { describe, it, expect } from 'vitest'
import type { Message } from '../types'
import { mergeFetchedMessages } from './mergeFetchedMessages'

function message(overrides: Partial<Message> = {}): Message {
  return {
    id: 'm1',
    content: 'Hello',
    role: 'user',
    timestamp: '2026-10-11T12:00:00Z',
    sources: [],
    ...overrides,
  }
}

const fetched = [
  message({ id: 'a', content: 'What is metastasis?' }),
  message({ id: 'b', role: 'assistant', content: 'Metastasis is…' }),
]

describe('mergeFetchedMessages', () => {
  it('returns the fetched list when nothing was added during the load', () => {
    const before = [message({ id: 'x', content: 'Previous conversation' })]
    expect(mergeFetchedMessages(before, fetched, before)).toBe(fetched)
  })

  it('drops the previous conversation\'s messages', () => {
    const previous = [message({ id: 'x', content: 'Earlier' })]
    expect(mergeFetchedMessages(previous, fetched, previous)).toBe(fetched)
  })

  it('keeps a question sent while the load was in flight', () => {
    const pending = message({ id: 'temp-1', content: 'What is lung cancer?' })
    expect(mergeFetchedMessages([pending], fetched, [])).toEqual([...fetched, pending])
  })

  it('keeps a reply that arrived before the load finished', () => {
    const exchange = [
      message({ id: 'u1', content: 'What is lung cancer?' }),
      message({ id: 'r1', role: 'assistant', content: 'Lung cancer is…' }),
    ]
    expect(mergeFetchedMessages(exchange, fetched, [])).toEqual([...fetched, ...exchange])
  })

  it('does not duplicate messages the fetched list already contains', () => {
    const saved = [...fetched, message({ id: 'u1', content: 'What is lung cancer?' })]
    const added = [message({ id: 'u1', content: 'What is lung cancer?' })]
    expect(mergeFetchedMessages(added, saved, [])).toBe(saved)
  })

  it('does not duplicate an unsaved question the server has already saved', () => {
    const saved = [...fetched, message({ id: 'c', content: 'What is lung cancer?' })]
    const pending = message({ id: 'temp-1', content: 'What is lung cancer?' })
    expect(mergeFetchedMessages([pending], saved, [])).toBe(saved)
  })
})
