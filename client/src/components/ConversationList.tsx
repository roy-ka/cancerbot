import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Link, Tooltip, Typography } from '@mui/material'
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
  const [logoutOpen, setLogoutOpen] = useState(false)

  const onclick = (id: string) => {
    setSelectedConversationId(id)
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Sticky header — never scrolls */}
      <Box sx={{ flexShrink: 0, px: 2, pt: 3, pb: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2, mt: '12px' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <PersonOutlineIcon fontSize="small" sx={{ color: 'rgba(255,255,255,0.6)' }} />
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Tooltip title="About">
              <IconButton size="small" onClick={() => setAboutOpen(true)} sx={{ color: 'rgba(255,255,255,0.6)' }}>
                <InfoOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <BugReportDialog compact />
            <Tooltip title="Logout">
              <IconButton size="small" onClick={() => setLogoutOpen(true)} sx={{ color: 'rgba(255,255,255,0.6)' }}>
                <LogoutIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
          {onCloseSidebar && (
            <button className="conversation-list-close-btn" onClick={onCloseSidebar}>
              ✕
            </button>
          )}
        </Box>
        <Typography className="conversation-title" pb={1}>
          Conversations
        </Typography>
      </Box>

      {/* Scrollable list */}
      <Box className="conversation-list-root" sx={{ px: 2 }}>
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

      {/* Back button — mobile only, never scrolls */}
      {onCloseSidebar && (
        <Box className="conversation-list-back-btn-wrapper" sx={{ flexShrink: 0, px: 2, pb: 2 }}>
          <button className="conversation-list-back-btn" onClick={onCloseSidebar}>
            ← Back to chat
          </button>
        </Box>
      )}

      <Dialog
        open={logoutOpen}
        onClose={() => setLogoutOpen(false)}
        slotProps={{
          backdrop: { sx: { backgroundColor: 'rgba(0,0,0,0.3)' } },
          paper: { sx: { backgroundColor: 'rgba(18,25,45,0.75)', backdropFilter: 'blur(18px)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 3 } },
        }}
      >
        <DialogTitle sx={{ color: 'rgba(255,255,255,0.92)' }}>Log out?</DialogTitle>
        <DialogContent sx={{ color: 'rgba(255,255,255,0.66)' }}>
          Are you sure you want to log out?
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2, gap: 1 }}>
          <Button onClick={() => setLogoutOpen(false)} sx={{ textTransform: 'none', color: 'rgba(255,255,255,0.6)' }}>
            No
          </Button>
          <Button
            onClick={() => { setLogoutOpen(false); onLogout?.() }}
            variant="contained"
            color="error"
            sx={{ textTransform: 'none' }}
          >
            Yes, log out
          </Button>
        </DialogActions>
      </Dialog>

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
