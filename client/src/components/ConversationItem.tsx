import { Grid, Typography } from '@mui/material'
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
    <Grid
      className={`conversation-item ${selected ? 'selected' : ''}`}
      onClick={onClick}
    >
      <Grid size={12}>
        <Typography className="conversation-item-title">
          {conversation.title}
        </Typography>
      </Grid>
      {(conversation.id !== 'new') && (
        <Grid container>
          <Grid size={7}>
            <Typography className="conversation-item-subtitle">
              {conversation.lastMessage
                ? conversation.lastMessage.length > 17
                  ? conversation.lastMessage.substring(0, 17) + '...'
                  : conversation.lastMessage
                : ''}
            </Typography>
          </Grid>
          <Grid size={1}>
            <Typography className="conversation-item-subtitle"> · </Typography>
          </Grid>
          <Grid size={4}>
            <Typography className="conversation-item-subtitle">
              {conversation.lastMessageTime}
            </Typography>
          </Grid>
        </Grid>
      )}
    </Grid>
  )
}
