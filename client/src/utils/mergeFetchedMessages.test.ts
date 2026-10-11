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
    conversationId: 'conv-1',
    ...overrides,
  }
}

const fetched = [
  message({ id: 'a', content: 'What is metastasis?' }),
  message({ id: 'b', role: 'assistant', content: 'Metastasis is…' }),
]

describe('mergeFetchedMessages', () => {
  it('returns the fetched list when nothing is pending', () => {
    expect(mergeFetchedMessages([], fetched, 'conv-1')).toBe(fetched)
  })

  it('keeps a question sent while the fetch was in flight', () => {
    const pending = message({ id: 'temp-1', content: 'What is lung cancer?' })
    const result = mergeFetchedMessages([pending], fetched, 'conv-1')
    expect(result).toEqual([...fetched, pending])
  })

  it('drops pending messages that belong to a different conversation', () => {
    const other = message({ id: 'temp-1', content: 'Old question', conversationId: 'conv-2' })
    expect(mergeFetchedMessages([other], fetched, 'conv-1')).toBe(fetched)
  })

  it('does not duplicate a question the server has already saved', () => {
    const saved = [...fetched, message({ id: 'c', content: 'What is lung cancer?' })]
    const pending = message({ id: 'temp-1', content: 'What is lung cancer?' })
    expect(mergeFetchedMessages([pending], saved, 'conv-1')).toBe(saved)
  })

  it('ignores the previous conversation\'s already-saved messages', () => {
    const previous = [message({ id: 'x', content: 'Earlier', conversationId: 'conv-1' })]
    expect(mergeFetchedMessages(previous, fetched, 'conv-1')).toBe(fetched)
  })
})
