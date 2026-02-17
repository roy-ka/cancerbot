import { Box } from '@mui/material'
import type { Message } from '../types'
export default function MessageItem({ message }: { message: Message }) {
  console.log('Rendering MessageItem:', message) // Debug log to check message content
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
        {message.content}
      </Box>
    </Box>
  )
}
