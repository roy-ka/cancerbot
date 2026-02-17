import { Box, Typography } from '@mui/material'
import type { Conversation } from '../types'

export default function ConversationItem({
  conversation,
  selected,
  onClick,
}: {
  conversation: Conversation
  selected: boolean
  onClick: () => void
}) {
  return (
    <Box
      className={`conversation-item ${selected ? 'selected' : ''}`}
      onClick={onClick}
    >
      <Typography className="conversation-item-title">
        {conversation.title}
      </Typography>
      <Typography className="conversation-item-subtitle">
        {conversation.lastMessage} · {conversation.lastMessageTime}
      </Typography>
    </Box>
  )
}
