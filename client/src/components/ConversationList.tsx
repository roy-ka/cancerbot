import { Box, IconButton, Tooltip, Typography } from '@mui/material'
import PersonOutlineIcon from '@mui/icons-material/PersonOutline'
import LogoutIcon from '@mui/icons-material/Logout'
import type { Conversation } from '../types'
import ConversationItem from './ConversationItem'
import BugReportDialog from './BugReportDialog'

const newConversation: Conversation = {
  id: 'new',
  title: 'New Conversation',
  lastMessage: '',
  lastMessageTime: '',
}

export default function ConversationList({
  conversations,
  selectedConversationId,
  setSelectedConversationId,
  onLogout,
  onCloseSidebar,
}: {
  conversations?: Conversation[]
  selectedConversationId?: string
  setSelectedConversationId: React.Dispatch<React.SetStateAction<string>>
  onLogout?: () => void
  onCloseSidebar?: () => void
}) {
  const onclick = (id: string) => {
    setSelectedConversationId(id)
  }

  return (
    <Box className="conversation-list-root" sx={{ px: 2, py: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <PersonOutlineIcon fontSize="small" sx={{ color: 'rgba(255,255,255,0.6)' }} />
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          {onCloseSidebar && (
            <button className="conversation-list-close-btn" onClick={onCloseSidebar}>
              ✕
            </button>
          )}
          <BugReportDialog compact />
          <Tooltip title="Logout">
            <IconButton size="small" onClick={onLogout} sx={{ color: 'rgba(255,255,255,0.6)' }}>
              <LogoutIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>
      <Typography className="conversation-title" pb={2}>
        Conversations
      </Typography>
      <ConversationItem
        conversation={newConversation}
        selected={selectedConversationId === 'new'}
        onClick={() => onclick('new')}
      />
      {conversations &&
        conversations.length > 0 &&
        conversations.map((conv) => (
          <ConversationItem
            key={conv.id}
            conversation={conv}
            selected={selectedConversationId === conv.id}
            onClick={() => onclick(conv.id)}
          />
        ))}
    </Box>
  )
}
