export const URL_RE = /https?:\/\/[^\s<>"'[\]]+/g

export function extractUrls(text: string): string[] {
  URL_RE.lastIndex = 0
  return Array.from(text.matchAll(URL_RE), (m) => m[0])
}
