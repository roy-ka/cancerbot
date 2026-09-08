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
  Tooltip,
  Typography,
} from '@mui/material'
import PersonOutlineIcon from '@mui/icons-material/PersonOutline'
import LogoutIcon from '@mui/icons-material/Logout'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import PrivacyTipOutlinedIcon from '@mui/icons-material/PrivacyTipOutlined'
import HelpOutlineIcon from '@mui/icons-material/HelpOutline'
import PersonRemoveOutlinedIcon from '@mui/icons-material/PersonRemoveOutlined'
import MedicalInformationOutlinedIcon from '@mui/icons-material/MedicalInformationOutlined'
import AlternateEmailOutlinedIcon from '@mui/icons-material/AlternateEmailOutlined'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import cancerbotIcon from '../assets/cancerbot_dark.svg'
import type { Conversation } from '../types'
import ConversationItem from './ConversationItem'
import BugReportDialog from './BugReportDialog'
import FindTrialsDialog from './FindTrialsDialog'

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
  onChangeEmail,
  onDeleteConversation,
  onCloseSidebar,
  onOpenGuide,
}: {
  conversations?: Conversation[]
  selectedConversationId?: string
  setSelectedConversationId: React.Dispatch<React.SetStateAction<string>>
  onLogout?: () => void
  onDeleteAccount?: () => Promise<string | null>
  onChangeEmail?: () => Promise<string | null>
  onDeleteConversation?: (id: string) => Promise<void>
  onCloseSidebar?: () => void
  onOpenGuide?: () => void
}) {
  const navigate = useNavigate()
  const [aboutOpen, setAboutOpen] = useState(false)
  const [logoutOpen, setLogoutOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleteLoading, setDeleteLoading] = useState(false)
  const [deleteRequested, setDeleteRequested] = useState(false)
  const [changeEmailOpen, setChangeEmailOpen] = useState(false)
  const [changeEmailError, setChangeEmailError] = useState<string | null>(null)
  const [changeEmailLoading, setChangeEmailLoading] = useState(false)
  const [changeEmailRequested, setChangeEmailRequested] = useState(false)
  const [menuAnchor, setMenuAnchor] = useState<null | HTMLElement>(null)
  const [deleteConvTarget, setDeleteConvTarget] = useState<{
    id: string
    title: string
  } | null>(null)

  const onclick = (id: string) => {
    setSelectedConversationId(id)
  }

  const openMenu = (e: React.MouseEvent<HTMLElement>) =>
    setMenuAnchor(e.currentTarget)
  const closeMenu = () => setMenuAnchor(null)

  const handleDeleteSubmit = async () => {
    if (!onDeleteAccount) return
    setDeleteLoading(true)
    setDeleteError(null)
    const err = await onDeleteAccount()
    setDeleteLoading(false)
    if (err) {
      setDeleteError(err)
    } else {
      setDeleteRequested(true)
    }
  }

  const handleChangeEmailSubmit = async () => {
    if (!onChangeEmail) return
    setChangeEmailLoading(true)
    setChangeEmailError(null)
    const err = await onChangeEmail()
    setChangeEmailLoading(false)
    if (err) {
      setChangeEmailError(err)
    } else {
      setChangeEmailRequested(true)
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
                onClick={() => {
                  closeMenu()
                  setLogoutOpen(true)
                }}
                sx={{ color: 'rgba(255,255,255,0.8)', gap: 1 }}
              >
                <ListItemIcon
                  sx={{ color: 'rgba(255,255,255,0.6)', minWidth: 32 }}
                >
                  <LogoutIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText primary="Logout" />
              </MenuItem>
              <MenuItem
                onClick={() => {
                  closeMenu()
                  navigate('/onboarding')
                }}
                sx={{ color: 'rgba(255,255,255,0.8)', gap: 1 }}
              >
                <ListItemIcon
                  sx={{ color: 'rgba(255,255,255,0.6)', minWidth: 32 }}
                >
                  <MedicalInformationOutlinedIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText primary="Health Profile" />
              </MenuItem>
              <MenuItem
                onClick={() => {
                  closeMenu()
                  setChangeEmailOpen(true)
                }}
                sx={{ color: 'rgba(255,255,255,0.8)', gap: 1 }}
              >
                <ListItemIcon
                  sx={{ color: 'rgba(255,255,255,0.6)', minWidth: 32 }}
                >
                  <AlternateEmailOutlinedIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText primary="Change Email" />
              </MenuItem>
              <MenuItem
                onClick={() => {
                  closeMenu()
                  setDeleteOpen(true)
                }}
                sx={{ color: 'rgba(255,100,100,0.9)', gap: 1 }}
              >
                <ListItemIcon
                  sx={{ color: 'rgba(255,100,100,0.8)', minWidth: 32 }}
                >
                  <PersonRemoveOutlinedIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText primary="Delete Account" />
              </MenuItem>
            </Menu>
          </Box>

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <FindTrialsDialog />
            <Tooltip title="Privacy">
              <IconButton
                size="small"
                component="a"
                href="/privacy"
                target="_blank"
                rel="noopener noreferrer"
                sx={{ color: 'rgba(255,255,255,0.6)' }}
              >
                <PrivacyTipOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            {onOpenGuide && (
              <Tooltip title="Icon guide">
                <IconButton
                  size="small"
                  aria-label="Icon guide"
                  data-testid="icon-guide-trigger"
                  onClick={onOpenGuide}
                  sx={{ color: 'rgba(255,255,255,0.6)' }}
                >
                  <HelpOutlineIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
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
      <Box
        className="conversation-list-root"
        sx={{ px: 3, spacing: 2, flexGrow: 1, overflowY: 'auto' }}
      >
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
              onDelete={(id, title) => setDeleteConvTarget({ id, title })}
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

      {/* Delete conversation confirmation */}
      <Dialog
        open={Boolean(deleteConvTarget)}
        onClose={() => setDeleteConvTarget(null)}
        slotProps={{
          backdrop: { sx: { backgroundColor: 'rgba(0,0,0,0.3)' } },
          paper: { sx: DIALOG_PAPER_SX },
        }}
      >
        <DialogTitle sx={{ color: 'rgba(255,255,255,0.92)' }}>
          Delete conversation?
        </DialogTitle>
        <DialogContent sx={{ color: 'rgba(255,255,255,0.66)' }}>
          Delete{' '}
          <Typography
            component="span"
            sx={{ color: 'rgba(255,255,255,0.9)', fontWeight: 600 }}
          >
            "{deleteConvTarget?.title}"
          </Typography>
          ? This cannot be undone.
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2, gap: 1 }}>
          <Button
            onClick={() => setDeleteConvTarget(null)}
            sx={{ textTransform: 'none', color: 'rgba(255,255,255,0.6)' }}
          >
            Cancel
          </Button>
          <Button
            onClick={async () => {
              if (!deleteConvTarget) return
              await onDeleteConversation?.(deleteConvTarget.id)
              setDeleteConvTarget(null)
            }}
            variant="contained"
            color="error"
            sx={{ textTransform: 'none' }}
          >
            Delete
          </Button>
        </DialogActions>
      </Dialog>

      {/* Logout confirmation */}
      <Dialog
        open={logoutOpen}
        onClose={() => setLogoutOpen(false)}
        slotProps={{
          backdrop: { sx: { backgroundColor: 'rgba(0,0,0,0.3)' } },
          paper: { sx: DIALOG_PAPER_SX },
        }}
      >
        <DialogTitle sx={{ color: 'rgba(255,255,255,0.92)' }}>
          Log out?
        </DialogTitle>
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
            onClick={() => {
              setLogoutOpen(false)
              onLogout?.()
            }}
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
        onClose={() => {
          setDeleteOpen(false)
          setDeleteError(null)
          setDeleteRequested(false)
        }}
        slotProps={{
          backdrop: { sx: { backgroundColor: 'rgba(0,0,0,0.3)' } },
          paper: { sx: DIALOG_PAPER_SX },
        }}
      >
        <DialogTitle sx={{ color: 'rgba(255,255,255,0.92)' }}>
          Delete Account
        </DialogTitle>
        <DialogContent
          sx={{
            display: 'flex',
            flexDirection: 'column',
            gap: 2,
            pt: '12px !important',
          }}
        >
          {deleteRequested ? (
            <Typography
              sx={{ color: 'rgba(255,255,255,0.66)', fontSize: '0.9rem' }}
            >
              We've sent a confirmation link to your email. Open it and enter
              your password to schedule deletion.
            </Typography>
          ) : (
            <>
              <Typography
                sx={{ color: 'rgba(255,255,255,0.66)', fontSize: '0.9rem' }}
              >
                We'll email you a link to confirm. Your account and
                conversations will be permanently deleted 7 days after you
                confirm — you can cancel any time before then just by logging
                in.
              </Typography>
              {deleteError && (
                <Typography sx={{ color: '#f44336', fontSize: '0.85rem' }}>
                  {deleteError}
                </Typography>
              )}
            </>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2, gap: 1 }}>
          <Button
            onClick={() => {
              setDeleteOpen(false)
              setDeleteError(null)
              setDeleteRequested(false)
            }}
            sx={{ textTransform: 'none', color: 'rgba(255,255,255,0.6)' }}
            disabled={deleteLoading}
          >
            {deleteRequested ? 'Close' : 'Cancel'}
          </Button>
          {!deleteRequested && (
            <Button
              onClick={handleDeleteSubmit}
              variant="contained"
              color="error"
              sx={{ textTransform: 'none' }}
              disabled={deleteLoading}
            >
              {deleteLoading ? 'Sending…' : 'Send Confirmation Email'}
            </Button>
          )}
        </DialogActions>
      </Dialog>

      {/* Change email confirmation */}
      <Dialog
        open={changeEmailOpen}
        onClose={() => {
          setChangeEmailOpen(false)
          setChangeEmailError(null)
          setChangeEmailRequested(false)
        }}
        slotProps={{
          backdrop: { sx: { backgroundColor: 'rgba(0,0,0,0.3)' } },
          paper: { sx: DIALOG_PAPER_SX },
        }}
      >
        <DialogTitle sx={{ color: 'rgba(255,255,255,0.92)' }}>
          Change Email
        </DialogTitle>
        <DialogContent
          sx={{
            display: 'flex',
            flexDirection: 'column',
            gap: 2,
            pt: '12px !important',
          }}
        >
          {changeEmailRequested ? (
            <Typography
              sx={{ color: 'rgba(255,255,255,0.66)', fontSize: '0.9rem' }}
            >
              We've sent a link to your current email. Open it to continue —
              you'll be asked to enter your new address there.
            </Typography>
          ) : (
            <>
              <Typography
                sx={{ color: 'rgba(255,255,255,0.66)', fontSize: '0.9rem' }}
              >
                We'll email a confirmation link to your current address.
                Opening it lets you enter the new email, which then needs its
                own confirmation before the change takes effect.
              </Typography>
              {changeEmailError && (
                <Typography sx={{ color: '#f44336', fontSize: '0.85rem' }}>
                  {changeEmailError}
                </Typography>
              )}
            </>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2, gap: 1 }}>
          <Button
            onClick={() => {
              setChangeEmailOpen(false)
              setChangeEmailError(null)
              setChangeEmailRequested(false)
            }}
            sx={{ textTransform: 'none', color: 'rgba(255,255,255,0.6)' }}
            disabled={changeEmailLoading}
          >
            {changeEmailRequested ? 'Close' : 'Cancel'}
          </Button>
          {!changeEmailRequested && (
            <Button
              onClick={handleChangeEmailSubmit}
              variant="contained"
              sx={{ textTransform: 'none' }}
              disabled={changeEmailLoading}
            >
              {changeEmailLoading ? 'Sending…' : 'Send Confirmation Email'}
            </Button>
          )}
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
            sx={{
              position: 'absolute',
              right: 8,
              top: 8,
              color: 'rgba(255,255,255,0.6)',
            }}
          >
            ✕
          </IconButton>
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 1.5,
              mb: 1.5,
            }}
          >
            <img
              src={cancerbotIcon}
              alt="Cancer-Bot logo"
              style={{ width: 48, height: 48, borderRadius: '50%' }}
            />
            <Typography
              variant="h4"
              fontWeight={700}
              sx={{ color: 'rgba(255,255,255,0.92)' }}
            >
              Cancer-Bot
            </Typography>
          </Box>
          <Typography
            variant="body2"
            sx={{ color: 'rgba(255,255,255,0.6)' }}
            gutterBottom
          >
            Created by Roy Kazaz
          </Typography>
          <Typography
            variant="body2"
            sx={{ color: 'rgba(255,255,255,0.6)' }}
            gutterBottom
          >
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
