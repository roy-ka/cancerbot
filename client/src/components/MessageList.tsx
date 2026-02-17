import { Box } from '@mui/material'
import type { Message } from '../types'
import MessageItem from './MessageItem'

export default function messageList({ messages }: { messages: Message[] }) {
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
    >
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
