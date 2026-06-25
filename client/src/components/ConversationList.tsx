import { Box, Dialog, DialogContent, IconButton, Link, Tooltip, Typography } from '@mui/material'
import PersonOutlineIcon from '@mui/icons-material/PersonOutline'
import LogoutIcon from '@mui/icons-material/Logout'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import { useState } from 'react'
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
  const [aboutOpen, setAboutOpen] = useState(false)

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
          <Tooltip title="About">
            <IconButton size="small" onClick={() => setAboutOpen(true)} sx={{ color: 'rgba(255,255,255,0.6)' }}>
              <InfoOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
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

      <Dialog open={aboutOpen} onClose={() => setAboutOpen(false)} aria-label="About CancerBot" PaperProps={{ sx: { borderRadius: 3, px: 1 } }}>
        <DialogContent sx={{ textAlign: 'center', py: 4, px: 5, position: 'relative' }}>
          <IconButton
            onClick={() => setAboutOpen(false)}
            size="small"
            sx={{ position: 'absolute', right: 8, top: 8 }}
          >
            ✕
          </IconButton>
          <Typography variant="h6" fontWeight={700} gutterBottom>
            CancerBot
          </Typography>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            Created by Roy Kazaz
          </Typography>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            Free to use
          </Typography>
          <Link href="mailto:kazazroy@gmail.com" variant="body2" underline="hover">
            kazazroy@gmail.com
          </Link>
        </DialogContent>
      </Dialog>
    </Box>
  )
}
