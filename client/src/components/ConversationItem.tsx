import { Grid, IconButton, Typography } from '@mui/material'
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
  onDelete?: (id: string) => void
}) {
  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation()
    onDelete?.(conversation.id)
  }

  return (
    <Grid
      className={`conversation-item ${selected ? 'selected' : ''}`}
      onClick={onClick}
    >
      <Grid container alignItems="center">
        <Grid size={10}>
          <Typography className="conversation-item-title">
            {conversation.title}
          </Typography>
        </Grid>
        {conversation.id !== 'new' && (
          <Grid size={2} display="flex" justifyContent="flex-end">
            <IconButton
              size="small"
              className="conversation-delete-btn"
              onClick={handleDelete}
              aria-label="Delete conversation"
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Grid>
        )}
      </Grid>
      {conversation.id !== 'new' && (
        <Grid container>
          <Grid size={7}>
            <Typography className="conversation-item-subtitle">
              {conversation.lastMessage.length > 17
                ? conversation.lastMessage.substring(0, 17) + '...'
                : conversation.lastMessage.length}
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
