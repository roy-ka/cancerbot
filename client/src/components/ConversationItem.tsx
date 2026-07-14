import { Box, Grid, IconButton, Typography } from '@mui/material'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import type { Conversation } from '../types'

export default function ConversationItem({
  conversation,
  selected,
  onClick,
  onDelete,
}: {
  conversation: Conversation
  selected: boolean
  onClick: () => void
  onDelete?: (id: string, title: string) => void
}) {
  return (
    <Grid
      className={`conversation-item ${selected ? 'selected' : ''}`}
      onClick={onClick}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Typography className="conversation-item-title">
          {conversation.title}
        </Typography>
        {conversation.id !== 'new' && onDelete && (
          <IconButton
            size="small"
            className="conversation-item-delete-btn"
            onClick={(e) => { e.stopPropagation(); onDelete(conversation.id, conversation.title) }}
            sx={{ color: 'rgba(255,255,255,0.5)', p: 0.5, flexShrink: 0 }}
          >
            <DeleteOutlineIcon fontSize="small" />
          </IconButton>
        )}
      </Box>
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
