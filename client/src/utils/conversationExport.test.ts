import { describe, it, expect } from 'vitest'
import type { Message, Source } from '../types'
import { conversationToMarkdown, conversationToPrintHtml } from './conversationExport'

function source(overrides: Partial<Source> = {}): Source {
  return {
    id: 'pmid:12345',
    url: null,
    text: '',
    name: 'A paper',
    ...overrides,
  }
}

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

describe('conversationToMarkdown', () => {
  it('includes a title heading and both roles', () => {
    const md = conversationToMarkdown('My Chat', [
      message({ role: 'user', content: 'What is cancer?' }),
      message({ role: 'assistant', content: 'Cancer is...' }),
    ])
    expect(md).toContain('# My Chat')
    expect(md).toContain('**You**')
    expect(md).toContain('What is cancer?')
    expect(md).toContain('**CancerBot**')
    expect(md).toContain('Cancer is...')
  })

  it('omits the Sources section when no message has sources', () => {
    const md = conversationToMarkdown('My Chat', [message()])
    expect(md).not.toContain('## Sources')
  })

  it('lists unique sources across messages, deduped by id', () => {
    const s1 = source({ id: 'pmid:1', name: 'Paper One' })
    const s2 = source({ id: 'pmid:2', name: 'Paper Two' })
    const md = conversationToMarkdown('My Chat', [
      message({ role: 'assistant', sources: [s1] }),
      message({ role: 'assistant', sources: [s1, s2] }),
    ])
    const occurrences = md.split('Paper One').length - 1
    expect(occurrences).toBe(1)
    expect(md).toContain('Paper Two')
  })

  it('reconstructs a real pubmed link from a bare pmid id', () => {
    const md = conversationToMarkdown('My Chat', [
      message({ role: 'assistant', sources: [source({ id: 'pmid:38175589', url: null, name: 'Paper' })] }),
    ])
    expect(md).toContain('[pmid:38175589 — Paper](https://pubmed.ncbi.nlm.nih.gov/38175589/)')
  })

  it('reconstructs a doi.org link from a bare doi id', () => {
    const md = conversationToMarkdown('My Chat', [
      message({
        role: 'assistant',
        sources: [source({ id: 'doi:10.1000/xyz', url: null, name: 'Paper' })],
      }),
    ])
    expect(md).toContain('[doi:10.1000/xyz — Paper](https://doi.org/10.1000/xyz)')
  })

  it('reconstructs a clinicaltrials.gov link from a bare nct id', () => {
    const md = conversationToMarkdown('My Chat', [
      message({
        role: 'assistant',
        sources: [source({ id: 'nct:NCT01729260', url: null, name: 'Trial' })],
      }),
    ])
    expect(md).toContain('[nct:NCT01729260 — Trial](https://clinicaltrials.gov/study/NCT01729260)')
  })

  it('uses a real http url as-is when already present', () => {
    const md = conversationToMarkdown('My Chat', [
      message({
        role: 'assistant',
        sources: [source({ id: 'url:abc', url: 'https://example.com/page', name: 'Page' })],
      }),
    ])
    expect(md).toContain('[url:abc — Page](https://example.com/page)')
  })

  it('falls back to plain text when no link can be resolved', () => {
    const md = conversationToMarkdown('My Chat', [
      message({ role: 'assistant', sources: [source({ id: '', url: null, name: 'Mystery' })] }),
    ])
    expect(md).toContain('- Mystery')
    expect(md).not.toContain('[Mystery]')
  })

  it('prefixes the label with the stable id so same-named sources stay distinguishable', () => {
    const md = conversationToMarkdown('My Chat', [
      message({
        role: 'assistant',
        sources: [
          source({ id: 'pmid:1', name: 'Overview', url: null }),
          source({ id: 'doi:10.5/x', name: 'Overview', url: null }),
        ],
      }),
    ])
    expect(md).toContain('pmid:1 — Overview')
    expect(md).toContain('doi:10.5/x — Overview')
  })

  it('does not duplicate the id when no better label exists', () => {
    const md = conversationToMarkdown('My Chat', [
      message({
        role: 'assistant',
        sources: [source({ id: 'pmid:1', name: 'pmid:1', title: undefined, url: null })],
      }),
    ])
    expect(md).toContain('[pmid:1](https://pubmed.ncbi.nlm.nih.gov/1/)')
    expect(md).not.toContain('pmid:1 — pmid:1')
  })
})

describe('conversationToPrintHtml', () => {
  it('escapes user-supplied content to prevent HTML injection', () => {
    const html = conversationToPrintHtml('My Chat', [
      message({ role: 'user', content: '<script>alert(1)</script>' }),
    ])
    expect(html).not.toContain('<script>alert(1)</script>')
    expect(html).toContain('&lt;script&gt;')
  })

  it('includes a Sources section with a real link', () => {
    const html = conversationToPrintHtml('My Chat', [
      message({ role: 'assistant', sources: [source({ id: 'pmid:1', url: null, name: 'Paper' })] }),
    ])
    expect(html).toContain('<h2>Sources</h2>')
    expect(html).toContain('href="https://pubmed.ncbi.nlm.nih.gov/1/"')
  })

  it('linkifies an in-body citation token using that message\'s own sources', () => {
    const html = conversationToPrintHtml('My Chat', [
      message({
        role: 'assistant',
        content: 'Cancer cells prefer glycolysis [pmid:38175589].',
        sources: [source({ id: 'pmid:38175589', url: null, name: 'Paper' })],
      }),
    ])
    expect(html).toContain('<a href="https://pubmed.ncbi.nlm.nih.gov/38175589/">[pmid:38175589]</a>')
  })

  it('leaves a citation token as plain text when its source is unknown', () => {
    const html = conversationToPrintHtml('My Chat', [
      message({ role: 'assistant', content: 'See [pmid:999].', sources: [] }),
    ])
    expect(html).toContain('[pmid:999]')
    expect(html).not.toContain('<a href')
  })

  it('does not linkify bracketed text that is not a real citation', () => {
    const html = conversationToPrintHtml('My Chat', [
      message({ role: 'user', content: 'What about [some note] here?', sources: [] }),
    ])
    expect(html).toContain('[some note]')
    expect(html).not.toContain('<a href')
  })

  it('produces a full, well-formed HTML document', () => {
    const html = conversationToPrintHtml('My Chat', [message()])
    expect(html).toContain('<!DOCTYPE html>')
    expect(html).toContain('<title>My Chat</title>')
  })

  it('includes the CancerBot logo in the header', () => {
    const html = conversationToPrintHtml('My Chat', [message()])
    expect(html).toContain('<img src="https://cancer-bot.com/cancerbot_light.png" alt="CancerBot">')
  })
})
