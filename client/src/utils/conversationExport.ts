import type { Message, Source } from '../types'

/** Best-effort real, clickable URL for a source. source.url is sometimes
 * just a bare pmid/doi (see _hit_to_entry in src/db/repositories/messeges.py)
 * rather than a navigable link — fine for the in-app citation popover, not
 * good enough for a standalone exported document, so this reconstructs a
 * canonical link from the stable id prefix when source.url isn't already
 * a real URL. */
function sourceHref(source: Source): string | null {
  if (source.url && /^https?:\/\//i.test(source.url)) return source.url

  const id = source.id || ''
  if (id.startsWith('pmid:')) return `https://pubmed.ncbi.nlm.nih.gov/${id.slice(5)}/`
  if (id.startsWith('doi:')) return `https://doi.org/${id.slice(4)}`
  if (id.startsWith('nct:')) return `https://clinicaltrials.gov/study/${id.slice(4)}`

  return source.url || null
}

/** "pmid:12345 — Paper title" — the bare name/title alone doesn't say which
 * source is which once there are several, so the stable id goes in front.
 * Skipped when the id and label are already the same string (nothing to
 * add, and no need to write it twice). */
function sourceLabel(source: Source): string {
  const label = source.title || source.name || source.id || 'Source'
  const id = source.id
  return id && id !== label ? `${id} — ${label}` : label
}

/** Unique sources across the whole conversation, in first-seen order. */
function collectSources(messages: Message[]): Source[] {
  const seen = new Set<string>()
  const out: Source[] = []
  for (const message of messages) {
    for (const source of message.sources ?? []) {
      const key = source.id || source.url || source.name
      if (!key || seen.has(key)) continue
      seen.add(key)
      out.push(source)
    }
  }
  return out
}

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
}

export function conversationToMarkdown(title: string, messages: Message[]): string {
  const lines: string[] = [`# ${title}`, '']

  for (const message of messages) {
    const who = message.role === 'user' ? 'You' : 'CancerBot'
    const when = formatTimestamp(message.timestamp)
    lines.push(`**${who}**${when ? ` — ${when}` : ''}`, '', message.content, '')
  }

  const sources = collectSources(messages)
  if (sources.length > 0) {
    lines.push('---', '', '## Sources', '')
    for (const source of sources) {
      const href = sourceHref(source)
      const label = sourceLabel(source)
      lines.push(href ? `- [${label}](${href})` : `- ${label}`)
    }
    lines.push('')
  }

  return lines.join('\n')
}

export function downloadMarkdown(filename: string, content: string): void {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// Matches a citation token like [pmid:12345] — mirrors MessageItem.tsx's
// in-app citation parsing, simplified to an exact id match (no punctuation
// trimming/normalization) since export content is already post-processed,
// stable-id text straight from the backend.
const CITATION_TOKEN_RE = /\[([^\]\s]+)\]/g

/** Turns [pmid:12345]-style citation tokens in already-escaped message text
 * into real links, using that message's own sources — the same info the
 * in-app citation chips use, but as plain <a> tags for a static document. */
function linkifyCitations(escapedContent: string, sources: Source[]): string {
  const byId = new Map(sources.map((s) => [s.id, s] as const))
  return escapedContent.replace(CITATION_TOKEN_RE, (fullMatch, id: string) => {
    const source = byId.get(id)
    if (!source) return fullMatch
    const href = sourceHref(source)
    return href ? `<a href="${href}">${fullMatch}</a>` : fullMatch
  })
}

export function conversationToPrintHtml(title: string, messages: Message[]): string {
  const body = messages
    .map((message) => {
      const who = message.role === 'user' ? 'You' : 'CancerBot'
      const when = formatTimestamp(message.timestamp)
      const content = linkifyCitations(escapeHtml(message.content), message.sources ?? [])
      return `
        <div class="message ${message.role}">
          <div class="meta"><strong>${who}</strong>${when ? ` — ${escapeHtml(when)}` : ''}</div>
          <div class="content">${content.replace(/\n/g, '<br/>')}</div>
        </div>
      `
    })
    .join('')

  const sources = collectSources(messages)
  const sourcesHtml =
    sources.length === 0
      ? ''
      : `<h2>Sources</h2><ul>${sources
          .map((source) => {
            const href = sourceHref(source)
            const label = escapeHtml(sourceLabel(source))
            return href ? `<li><a href="${href}">${label}</a></li>` : `<li>${label}</li>`
          })
          .join('')}</ul>`

  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>${escapeHtml(title)}</title>
<style>
  body { font-family: Arial, Helvetica, sans-serif; color: #222; max-width: 800px; margin: 40px auto; padding: 0 20px; }
  .header { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
  .header img { width: 32px; height: 32px; }
  h1 { font-size: 20px; margin: 0; }
  h2 { font-size: 16px; margin-top: 32px; border-top: 1px solid #ddd; padding-top: 16px; }
  .message { margin-bottom: 20px; }
  .message.user .meta { color: #4A6184; }
  .message.assistant .meta { color: #2E7D32; }
  .meta { font-size: 12px; margin-bottom: 4px; }
  .content { white-space: pre-wrap; line-height: 1.5; }
  ul { padding-left: 20px; }
  li { margin-bottom: 4px; font-size: 13px; }
  a { color: #4A6184; }
  @media print { body { margin: 0; } }
</style>
</head>
<body>
<div class="header">
  <img src="https://cancer-bot.com/cancerbot_light.png" alt="CancerBot">
  <h1>${escapeHtml(title)}</h1>
</div>
${body}
${sourcesHtml}
</body>
</html>`
}

/** Opens a new window with a print-styled rendering and triggers the
 * browser's print dialog — "Save as PDF" there is the actual PDF output.
 * Avoids pulling in a PDF-generation library for a one-click download. */
export function printConversationAsPdf(title: string, messages: Message[]): void {
  const html = conversationToPrintHtml(title, messages)
  const win = window.open('', '_blank')
  if (!win) return
  win.document.open()
  win.document.write(html)
  win.document.close()
  win.focus()
  win.print()
}
