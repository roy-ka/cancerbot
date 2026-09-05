import { Alert, Box, CircularProgress, Snackbar } from '@mui/material'
import type { Message } from '../types'
import MessageItem from './MessageItem'
type NewConversation = { id: string; title: string; lastMessage: string | null; lastMessageTime: string | null }
import ConversationIntro from './ConversationIntro'
import { useCallback, useEffect, useRef, useState } from 'react'
import { crabReadingSendIcon, crabSearchingBooksAnimated } from '../assets'

const getStageMessage = (stage: string): string => {
  const messages: Record<string, string> = {
    loading_conversation: 'Loading conversation...',
    saving_user_message: 'Saving your message...',
    retrieving_context: 'Retrieving context...',
    building_prompt: 'Building prompt...',
    generating_answer: 'Generating answer...',
    re_retrieving_context: 'Re-retrieving context...',
    rebuilding_prompt: 'Rebuilding prompt...',
    re_generating_answer: 'Re-generating answer...',
    fallback_triggered: 'Searching for additional sources...',
    analyzing_recent_messages: 'Analyzing recent messages...',
    extracting_search_terms: 'Extracting search terms...',
    terms_ready: 'Search terms ready...',
    searching_the_internet: 'Searching the internet...',
    found_sources: 'Found sources...',
    embedding_and_indexing_sources: 'Indexing sources...',
    sources_indexed: 'Sources indexed...',
  }
  return messages[stage] || stage
}

export default function MessageList({
  messages,
  onLoadOlder,
  hasOlder = false,
  isLoadingOlder = false,
  currentStage = null,
  streamingContent = null,
  onExampleClick,
  conversationId,
  onSplit,
  onContinue,
  continuingMessageId,
  continuingText,
}: {
  messages: Message[]
  onLoadOlder?: () => Promise<boolean> | boolean
  hasOlder?: boolean
  isLoadingOlder?: boolean
  currentStage?: string | null
  streamingContent?: string | null
  onExampleClick?: (text: string) => void
  conversationId?: string
  onSplit?: (conversation: NewConversation) => void
  onContinue?: (messageId: string) => void
  continuingMessageId?: string | null
  continuingText?: string
}) {
  const [noOlderOpen, setNoOlderOpen] = useState(false)
  const lastTriggerRef = useRef<number>(0)
  const stageIndicatorRef = useRef<HTMLDivElement>(null)
  const streamingMessageRef = useRef<HTMLDivElement>(null)
  const prevStageRef = useRef<string | null>(null)
  const prevStreamingRef = useRef<string | null>(null)

  useEffect(() => {
    if (currentStage && !prevStageRef.current) {
      stageIndicatorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
    prevStageRef.current = currentStage
  }, [currentStage])

  useEffect(() => {
    if (streamingContent !== null && prevStreamingRef.current === null) {
      streamingMessageRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
    prevStreamingRef.current = streamingContent
  }, [streamingContent])

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
        <ConversationIntro onExampleClick={onExampleClick} />
      )}
      {messages.map((message) => (
        <MessageItem
          message={message}
          key={message.id || 'new'}
          conversationId={conversationId}
          onSplit={onSplit}
          onContinue={onContinue}
          isContinuing={!!message.id && message.id === continuingMessageId}
          continuingText={message.id === continuingMessageId ? continuingText : undefined}
        />
      ))}
      {streamingContent !== null ? (
        <Box
          ref={streamingMessageRef}
          sx={{
            mb: 2,
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'flex-start',
          }}
        >
          <Box
            className="message-bubble-assistant"
            sx={{
              maxWidth: { xs: '90%', sm: '70%' },
              px: 3,
              py: 2,
              backgroundColor: 'rgba(255,255,255,0.15)',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {streamingContent}
            <Box
              component="span"
              sx={{
                display: 'inline-block',
                width: '0.5em',
                height: '1.1em',
                backgroundColor: 'currentColor',
                ml: '2px',
                verticalAlign: 'text-bottom',
                animation: 'blink 1s step-end infinite',
                '@keyframes blink': {
                  '0%, 100%': { opacity: 1 },
                  '50%': { opacity: 0 },
                },
              }}
            />
          </Box>
        </Box>
      ) : currentStage ? (
        <Box
          ref={stageIndicatorRef}
          sx={{
            mt: 2,
            display: 'flex',
            alignItems: 'center',
            gap: 1.5,
            color: 'rgba(255,255,255,0.6)',
            fontSize: '0.85rem',
          }}
        >
          <Box component="img" src={crabSearchingBooksAnimated} alt="" sx={{ width: 36, height: 36 }} />
          <span>{getStageMessage(currentStage)}</span>
        </Box>
      ) : (
        <Box sx={{ mt: 2, display: 'flex', justifyContent: 'flex-start' }}>
          <Box component="img" src={crabReadingSendIcon} alt="" sx={{ width: 32, height: 32 }} />
        </Box>
      )}
    </Box>
  )
}
