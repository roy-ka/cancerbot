import { Box, Link, Typography } from '@mui/material'
import React, { useMemo } from 'react'
import type { Message, Source } from '../types'
import MessageSourceItem from './MessageSourceItem'
import GroupedMessageSourceItem from './GroupedMessageSourceItem'
// Fresh regex per call — avoids shared lastIndex state across concurrent renders
const URL_LOCAL_RE = () => /https?:\/\/[^\s<>"'()[\]{}]+/g
// Trailing punctuation that commonly appears after a URL in prose but isn't part of it
const TRAILING_PUNCT = /[.,;:!?)]+$/

function renderTextWithLinks(text: string, keyPrefix: string): React.ReactNode[] {
  const re = URL_LOCAL_RE()
  const nodes: React.ReactNode[] = []
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    const href = m[0].replace(TRAILING_PUNCT, '')
    const matchEnd = m.index + m[0].length
    const trailingLen = m[0].length - href.length
    if (m.index > last) nodes.push(text.slice(last, m.index))
    nodes.push(
      <Link
        key={`${keyPrefix}-url-${m.index}`}
        href={href}
        rel="noopener noreferrer"
        onClick={(e) => {
          e.preventDefault()
          window.open(href, '_blank', 'noopener,noreferrer')
        }}
        sx={{ wordBreak: 'break-all', cursor: 'pointer' }}
      >
        {href}
      </Link>,
    )
    if (trailingLen > 0) nodes.push(text.slice(matchEnd - trailingLen, matchEnd))
    last = matchEnd
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

export default function MessageItem({ message }: { message: Message }) {
  const normalizeRefId = (raw: string) => {
    let id = (raw ?? '').trim()

    // Remove invisible / zero-width chars that can break key matching
    id = id.replace(/[\u200B-\u200D\uFEFF]/g, '')

    // If the id was accidentally stored with brackets, strip them.
    if (id.startsWith('[') && id.endsWith(']')) id = id.slice(1, -1)

    // Also strip any stray leading/trailing bracket characters.
    id = id.replace(/^\[+/, '').replace(/\]+$/, '')

    // Strip only common trailing punctuation that may appear near/inside brackets.
    id = id.replace(/[.,;]+$/, '')

    // Normalize specific prefixes
    if (id.startsWith('doi:')) id = 'doi:' + id.slice(4).toLowerCase()

    if (id.startsWith('pmid:')) {
      // Accept both pmid:123 and pmid:123.0 (backend sometimes stores .0)
      const rest = id.slice(5).trim()
      id = 'pmid:' + rest.replace(/\.0$/, '')
    }

    if (id.startsWith('url:')) {
      const rest = id.slice(4).trim()
      id = 'url:' + rest.toLowerCase()
    }

    return id
  }

  const mergedSources: Record<string, Source> = useMemo(() => {
    return (message.sources ?? []).reduce(
      (h, item) => {
        const k = normalizeRefId(item.id)
        h[k] = item
        // Also index by the raw id (after trimming/bracket stripping) in case the server returns inconsistent formatting
        h[normalizeRefId(String(item.id))] = item
        return h
      },
      {} as Record<string, Source>,
    )
  }, [message.sources])
  // Build a Typography node that contains text + clickable citation tokens like [C1], [pmid:...]
  const mesegeEnrichedText = useMemo(() => {
    const text = message.content ?? ''
    const parts: React.ReactNode[] = []

    // First, find all citations and their positions
    const re = /\[([^\]\s]+)\]/g
    const citations: Array<{ id: string; start: number; end: number; full: string }> = []
    let match: RegExpExecArray | null

    while ((match = re.exec(text)) !== null) {
      const full = match[0]
      const id = normalizeRefId(match[1])
      citations.push({
        id,
        start: match.index,
        end: match.index + full.length,
        full,
      })
    }

    // Group consecutive citations
    const groups: Array<{ citations: typeof citations; start: number; end: number }> = []
    let currentGroup: typeof citations = []
    let groupStart = 0

    for (let i = 0; i < citations.length; i++) {
      const citation = citations[i]
      if (i === 0) {
        currentGroup = [citation]
        groupStart = citation.start
      } else {
        // Check if consecutive (no text between previous citation end and this start)
        if (citation.start === citations[i - 1].end) {
          currentGroup.push(citation)
        } else {
          groups.push({
            citations: currentGroup,
            start: groupStart,
            end: citations[i - 1].end,
          })
          currentGroup = [citation]
          groupStart = citation.start
        }
      }
    }
    if (currentGroup.length > 0) {
      groups.push({
        citations: currentGroup,
        start: groupStart,
        end: citations[citations.length - 1].end,
      })
    }

    // Build parts with groups surrounded by brackets
    let lastIndex = 0
    for (const group of groups) {
      // Add text before group
      if (group.start > lastIndex) {
        parts.push(...renderTextWithLinks(text.slice(lastIndex, group.start), `${message.id}-pre-${lastIndex}`))
      }

      // Resolve citations before pushing brackets — skip the group entirely if none resolve.
      const groupSources: Source[] = []
      const displayTexts: string[] = []

      for (const citation of group.citations) {
        const source = mergedSources[normalizeRefId(citation.id)]
        if (source) {
          groupSources.push(source)
          displayTexts.push(citation.full.slice(1, -1)) // Remove brackets from display
        }
      }

      if (groupSources.length === 1) {
        parts.push('[')
        parts.push(
          <MessageSourceItem
            key={`${message.id}-${group.start}`}
            source={groupSources[0]}
            text={displayTexts[0]}
          />,
        )
        parts.push(']')
      } else if (groupSources.length > 1) {
        parts.push('[')
        parts.push(
          <GroupedMessageSourceItem
            key={`${message.id}-${group.start}`}
            sources={groupSources}
            displayTexts={displayTexts}
          />,
        )
        parts.push(']')
      }

      lastIndex = group.end
    }

    // Add remaining text
    if (lastIndex < text.length) {
      parts.push(...renderTextWithLinks(text.slice(lastIndex), `${message.id}-tail`))
    }

    return <Typography sx={{ whiteSpace: 'pre-wrap' }}>{parts}</Typography>
  }, [message.content, mergedSources, message.id])

  return (
    <Box
      sx={{
        mb: 2,
        display: 'flex',
        flexDirection: message.role === 'user' ? 'row-reverse' : 'row',
        alignItems: 'flex-start',
      }}
      key={message.id}
    >
      <Box
        key={message.id}
        sx={{
          maxWidth: '70%',
          px: 3,
          py: 2,
          borderRadius: 2,
          backgroundColor:
            message.role === 'user'
              ? 'rgba(255,255,255,0.1)'
              : 'rgba(255,255,255,0.15)',
        }}
      >
        {mesegeEnrichedText}
      </Box>
    </Box>
  )
}
