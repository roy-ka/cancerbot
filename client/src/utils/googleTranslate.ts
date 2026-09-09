import type { Message } from '../types'

/** Strip [source1]/[pmid:...]/[doi:...] citation tokens — Google Translate
 * would otherwise try (and mangle) translating them too. */
function stripCitations(text: string): string {
  return text.replace(/\[[^\]\s]+\]/g, '').trim()
}

function targetLanguage(): string {
  return (navigator.language || 'en').split('-')[0]
}

/** Opens the given text in Google Translate, in the browser's language. */
export function openInGoogleTranslate(text: string): void {
  const plainText = stripCitations(text)
  const url = `https://translate.google.com/?sl=auto&tl=${encodeURIComponent(targetLanguage())}&text=${encodeURIComponent(plainText)}&op=translate`
  window.open(url, '_blank', 'noopener,noreferrer')
}

/** Opens the whole conversation (every message, in order) in Google
 * Translate as a single "You: ... / CancerBot: ..." transcript. */
export function openConversationInGoogleTranslate(messages: Message[]): void {
  const transcript = messages
    .map((m) => `${m.role === 'user' ? 'You' : 'CancerBot'}: ${stripCitations(m.content ?? '')}`)
    .join('\n\n')
  openInGoogleTranslate(transcript)
}
