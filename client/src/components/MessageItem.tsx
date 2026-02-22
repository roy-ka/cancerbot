import { Box, Typography } from '@mui/material'
import React, { useMemo } from 'react'
import type { Message, SourceAndClaim } from '../types'
import MessageSourceItem from './MessageSourceItem'

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

  const mergedSourcesAndClaims: Record<string, SourceAndClaim> = useMemo(() => {
    return [...(message.sources ?? []), ...(message.claims ?? [])].reduce(
      (h, item) => {
        const k = normalizeRefId(item.id)
        h[k] = item
        // Also index by the raw id (after trimming/bracket stripping) in case the server returns inconsistent formatting
        h[normalizeRefId(String(item.id))] = item
        return h
      },
      {} as Record<string, SourceAndClaim>,
    )
  }, [message.sources, message.claims])
  // Build a Typography node that contains text + clickable citation tokens like [C1], [pmid:...]
  const mesegeEnrichedText = useMemo(() => {
    const text = message.content ?? ''
    const parts: React.ReactNode[] = []

    // Capture anything inside brackets: [ ... ]
    const re = /\[([^\]\s]+)\]/g
    let lastIndex = 0
    let match: RegExpExecArray | null

    const addText = (chunk: string) => {
      if (!chunk) return
      parts.push(chunk)
    }

    const addLink = (id: string, token: string, key: string) => {
      const source = mergedSourcesAndClaims[normalizeRefId(id)]
      const safeSource: SourceAndClaim = source ?? {
        id,
        url: null,
        text: 'Source details not loaded yet.',
      }

      parts.push(
        <MessageSourceItem key={key} source={safeSource} text={token} />,
      )
    }

    while ((match = re.exec(text)) !== null) {
      const full = match[0] // e.g. "[C1]"
      const id = normalizeRefId(match[1])
      const start = match.index
      const end = start + full.length
      addText(text.slice(lastIndex, start))
      addLink(id, full, `${message.id}-${start}-${id}`)
      lastIndex = end
    }

    addText(text.slice(lastIndex))

    return <Typography sx={{ whiteSpace: 'pre-wrap' }}>{parts}</Typography>
  }, [message.content, mergedSourcesAndClaims, message.id])

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
