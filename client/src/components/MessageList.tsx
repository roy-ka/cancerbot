import { Alert, Box, CircularProgress, Snackbar } from '@mui/material'
import type { Message } from '../types'
import MessageItem from './MessageItem'
import { useCallback, useRef, useState } from 'react'

export default function MessageList({
  messages,
  onLoadOlder,
  hasOlder = false,
  isLoadingOlder = false,
}: {
  messages: Message[]
  onLoadOlder?: () => Promise<boolean> | boolean
  hasOlder?: boolean
  isLoadingOlder?: boolean
}) {
  const [noOlderOpen, setNoOlderOpen] = useState(false)
  const lastTriggerRef = useRef<number>(0)

  const handleScroll = useCallback(
    async (e: React.UIEvent<HTMLDivElement>) => {
      // Only trigger when reaching the very top
      if (!onLoadOlder) return
      if (isLoadingOlder) return

      const el = e.currentTarget
      if (el.scrollTop > 0) return

      // Basic throttle to avoid spamming while momentum/elastic scrolling
      const now = Date.now()
      if (now - lastTriggerRef.current < 600) return
      lastTriggerRef.current = now

      if (!hasOlder) {
        setNoOlderOpen(true)
        return
      }

      try {
        const loaded = await Promise.resolve(onLoadOlder())
        if (!loaded) setNoOlderOpen(true)
      } catch {
        // If load fails, don't claim "no older". Let the caller log error.
      }
    },
    [onLoadOlder, hasOlder, isLoadingOlder],
  )

  return (
    <Box
      sx={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',

        overflowY: 'auto',
        px: { xs: 2, md: 4 },
        py: 3,
      }}
      onScroll={handleScroll}
    >
      <Snackbar
        open={noOlderOpen}
        autoHideDuration={1800}
        onClose={() => setNoOlderOpen(false)}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Alert
          severity="info"
          variant="filled"
          onClose={() => setNoOlderOpen(false)}
          sx={{ width: '100%' }}
        >
          No older messages
        </Alert>
      </Snackbar>

      {isLoadingOlder && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 1 }}>
          <CircularProgress size={18} />
        </Box>
      )}

      {messages.length === 0 && (
        <Box
          sx={{
            mt: 4,
            textAlign: 'center',
            color: 'rgba(255,255,255,0.6)',
          }}
        >
          No messages yet. Start the conversation!
        </Box>
      )}
      {messages.map((message) => (
        <MessageItem message={message} key={message.id || 'new'} />
      ))}
    </Box>
  )
}
