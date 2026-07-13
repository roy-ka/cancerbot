import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Link,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import PersonOutlineIcon from '@mui/icons-material/PersonOutline'
import LogoutIcon from '@mui/icons-material/Logout'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import PersonRemoveOutlinedIcon from '@mui/icons-material/PersonRemoveOutlined'
import { useState } from 'react'
import cancerbotIcon from '../assets/cancerbot_dark.svg'
import type { Conversation } from '../types'
import ConversationItem from './ConversationItem'
import BugReportDialog from './BugReportDialog'

const newConversation: Conversation = {
  id: 'new',
  title: 'New Conversation',
  lastMessage: '',
  lastMessageTime: '',
}

const DIALOG_PAPER_SX = {
  backgroundColor: 'rgba(18,25,45,0.75)',
  backdropFilter: 'blur(18px)',
  border: '1px solid rgba(255,255,255,0.1)',
  borderRadius: 3,
}

export default function ConversationList({
  conversations,
  selectedConversationId,
  setSelectedConversationId,
  onLogout,
  onDeleteAccount,
  onCloseSidebar,
}: {
  conversations?: Conversation[]
  selectedConversationId?: string
  setSelectedConversationId: React.Dispatch<React.SetStateAction<string>>
  onLogout?: () => void
  onDeleteAccount?: (password: string) => Promise<string | null>
  onCloseSidebar?: () => void
}) {
  const [aboutOpen, setAboutOpen] = useState(false)
  const [logoutOpen, setLogoutOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deletePassword, setDeletePassword] = useState('')
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleteLoading, setDeleteLoading] = useState(false)
  const [menuAnchor, setMenuAnchor] = useState<null | HTMLElement>(null)

  const onclick = (id: string) => {
    setSelectedConversationId(id)
  }

  const openMenu = (e: React.MouseEvent<HTMLElement>) => setMenuAnchor(e.currentTarget)
  const closeMenu = () => setMenuAnchor(null)

  const handleDeleteSubmit = async () => {
    if (!onDeleteAccount) return
    setDeleteLoading(true)
    setDeleteError(null)
    const err = await onDeleteAccount(deletePassword)
    setDeleteLoading(false)
    if (err) {
      setDeleteError(err)
    } else {
      setDeleteOpen(false)
      setDeletePassword('')
    }
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Sticky header — never scrolls */}
      <Box sx={{ flexShrink: 0, px: 2, pt: 3, pb: 1 }}>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            mb: 2,
            mt: '12px',
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Tooltip title="Account">
              <IconButton
                size="small"
                onClick={openMenu}
                sx={{ color: 'rgba(255,255,255,0.6)' }}
              >
                <PersonOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <Menu
              anchorEl={menuAnchor}
              open={Boolean(menuAnchor)}
              onClose={closeMenu}
              slotProps={{
                paper: {
                  sx: {
                    backgroundColor: 'rgb(18,25,45)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: 2,
                    minWidth: 180,
                  },
                },
              }}
            >
              <MenuItem
                onClick={() => { closeMenu(); setLogoutOpen(true) }}
                sx={{ color: 'rgba(255,255,255,0.8)', gap: 1 }}
              >
                <ListItemIcon sx={{ color: 'rgba(255,255,255,0.6)', minWidth: 32 }}>
                  <LogoutIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText primary="Logout" />
              </MenuItem>
              <MenuItem
                onClick={() => { closeMenu(); setDeleteOpen(true) }}
                sx={{ color: 'rgba(255,100,100,0.9)', gap: 1 }}
              >
                <ListItemIcon sx={{ color: 'rgba(255,100,100,0.8)', minWidth: 32 }}>
                  <PersonRemoveOutlinedIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText primary="Delete Account" />
              </MenuItem>
            </Menu>
          </Box>

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Tooltip title="About">
              <IconButton
                size="small"
                onClick={() => setAboutOpen(true)}
                sx={{ color: 'rgba(255,255,255,0.6)' }}
              >
                <InfoOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <BugReportDialog compact />
          </Box>

          {onCloseSidebar && (
            <button
              className="conversation-list-close-btn"
              onClick={onCloseSidebar}
            >
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
        <Box
          className="conversation-list-back-btn-wrapper"
          sx={{ flexShrink: 0, px: 2, pb: 2 }}
        >
          <button
            className="conversation-list-back-btn"
            onClick={onCloseSidebar}
          >
            ← Back to chat
          </button>
        </Box>
      )}

      {/* Logout confirmation */}
      <Dialog
        open={logoutOpen}
        onClose={() => setLogoutOpen(false)}
        slotProps={{
          backdrop: { sx: { backgroundColor: 'rgba(0,0,0,0.3)' } },
          paper: { sx: DIALOG_PAPER_SX },
        }}
      >
        <DialogTitle sx={{ color: 'rgba(255,255,255,0.92)' }}>Log out?</DialogTitle>
        <DialogContent sx={{ color: 'rgba(255,255,255,0.66)' }}>
          Are you sure you want to log out?
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2, gap: 1 }}>
          <Button
            onClick={() => setLogoutOpen(false)}
            sx={{ textTransform: 'none', color: 'rgba(255,255,255,0.6)' }}
          >
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

      {/* Delete account confirmation */}
      <Dialog
        open={deleteOpen}
        onClose={() => { setDeleteOpen(false); setDeletePassword(''); setDeleteError(null) }}
        slotProps={{
          backdrop: { sx: { backgroundColor: 'rgba(0,0,0,0.3)' } },
          paper: { sx: DIALOG_PAPER_SX },
        }}
      >
        <DialogTitle sx={{ color: 'rgba(255,255,255,0.92)' }}>Delete Account</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '12px !important' }}>
          <Typography sx={{ color: 'rgba(255,255,255,0.66)', fontSize: '0.9rem' }}>
            This will permanently delete your account and all conversations. Enter your password to confirm.
          </Typography>
          <TextField
            type="password"
            label="Password"
            size="small"
            value={deletePassword}
            onChange={(e) => { setDeletePassword(e.target.value); setDeleteError(null) }}
            onKeyDown={(e) => { if (e.key === 'Enter') handleDeleteSubmit() }}
            error={!!deleteError}
            helperText={deleteError ?? ''}
            autoFocus
            sx={{
              '& .MuiOutlinedInput-root': { color: 'rgba(255,255,255,0.9)' },
              '& .MuiInputLabel-root': { color: 'rgba(255,255,255,0.5)' },
              '& .MuiOutlinedInput-notchedOutline': { borderColor: 'rgba(255,255,255,0.2)' },
              '& .MuiFormHelperText-root': { color: '#f44336' },
            }}
          />
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2, gap: 1 }}>
          <Button
            onClick={() => { setDeleteOpen(false); setDeletePassword(''); setDeleteError(null) }}
            sx={{ textTransform: 'none', color: 'rgba(255,255,255,0.6)' }}
            disabled={deleteLoading}
          >
            Cancel
          </Button>
          <Button
            onClick={handleDeleteSubmit}
            variant="contained"
            color="error"
            sx={{ textTransform: 'none' }}
            disabled={!deletePassword || deleteLoading}
          >
            {deleteLoading ? 'Deleting…' : 'Delete Account'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* About */}
      <Dialog
        open={aboutOpen}
        onClose={() => setAboutOpen(false)}
        aria-label="About Cancer-Bot"
        maxWidth="sm"
        fullWidth
        slotProps={{
          backdrop: { sx: { backgroundColor: 'rgba(0,0,0,0.3)' } },
          paper: {
            sx: {
              backgroundColor: 'rgb(18,25,45)',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 3,
              px: 1,
            },
          },
        }}
      >
        <DialogContent
          sx={{ textAlign: 'center', py: 6, px: 6, position: 'relative' }}
        >
          <IconButton
            onClick={() => setAboutOpen(false)}
            size="small"
            sx={{ position: 'absolute', right: 8, top: 8, color: 'rgba(255,255,255,0.6)' }}
          >
            ✕
          </IconButton>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1.5, mb: 1.5 }}>
            <img src={cancerbotIcon} alt="Cancer-Bot logo" style={{ width: 48, height: 48, borderRadius: '50%' }} />
            <Typography variant="h4" fontWeight={700} sx={{ color: 'rgba(255,255,255,0.92)' }}>
              Cancer-Bot
            </Typography>
          </Box>
          <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.6)' }} gutterBottom>
            Created by Roy Kazaz
          </Typography>
          <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.6)' }} gutterBottom>
            Free to use
          </Typography>
          <Link
            href="mailto:kazazroy@gmail.com"
            variant="body2"
            underline="hover"
            sx={{ color: 'rgba(255,255,255,0.7)' }}
          >
            kazazroy@gmail.com
          </Link>
        </DialogContent>
      </Dialog>
    </Box>
  )
}
