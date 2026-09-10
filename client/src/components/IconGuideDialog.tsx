import type { ReactNode } from 'react'
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
} from '@mui/material'
import PersonOutlineIcon from '@mui/icons-material/PersonOutline'
import LogoutIcon from '@mui/icons-material/Logout'
import PersonRemoveOutlinedIcon from '@mui/icons-material/PersonRemoveOutlined'
import TravelExploreIcon from '@mui/icons-material/TravelExplore'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import HelpOutlineIcon from '@mui/icons-material/HelpOutline'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import TranslateIcon from '@mui/icons-material/Translate'
import BiotechIcon from '@mui/icons-material/Biotech'
import MedicalInformationOutlinedIcon from '@mui/icons-material/MedicalInformationOutlined'
import AlternateEmailOutlinedIcon from '@mui/icons-material/AlternateEmailOutlined'
import PrivacyTipOutlinedIcon from '@mui/icons-material/PrivacyTipOutlined'
import FeedbackOutlinedIcon from '@mui/icons-material/FeedbackOutlined'
import {
  GUIDE_AREAS,
  entriesForArea,
  type IconKey,
  type GuideEntry,
} from '../utils/iconGuide'

/**
 * Icons shown in the guide. This is an exhaustive Record, so adding an IconKey
 * without an icon here is a type error rather than a blank row at runtime.
 * Entries that carry an `emoji` render that instead (the real UI uses an emoji
 * for those too), so their value here is only a fallback.
 */
const ICONS: Record<IconKey, ReactNode> = {
  account: <PersonOutlineIcon fontSize="small" />,
  logout: <LogoutIcon fontSize="small" />,
  healthProfile: <MedicalInformationOutlinedIcon fontSize="small" />,
  changeEmail: <AlternateEmailOutlinedIcon fontSize="small" />,
  deleteAccount: <PersonRemoveOutlinedIcon fontSize="small" />,
  findTrials: <TravelExploreIcon fontSize="small" />,
  privacy: <PrivacyTipOutlinedIcon fontSize="small" />,
  about: <InfoOutlinedIcon fontSize="small" />,
  guide: <HelpOutlineIcon fontSize="small" />,
  feedback: <FeedbackOutlinedIcon fontSize="small" />,
  closeSidebar: null,
  toggleSidebar: null,
  deleteConversation: <DeleteOutlineIcon fontSize="small" />,
  translate: <TranslateIcon fontSize="small" />,
  trialBadge: <BiotechIcon fontSize="small" />,
  citation: (
    <Box component="span" sx={{ fontWeight: 700, color: 'primary.main' }}>
      pmid:
    </Box>
  ),
  send: null,
}

function GuideRow({ entry }: { entry: GuideEntry }) {
  return (
    <Box
      data-testid="icon-guide-row"
      sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5, py: 0.75 }}
    >
      <Box
        sx={{
          flexShrink: 0,
          width: 28,
          display: 'flex',
          justifyContent: 'center',
          color: 'rgba(255,255,255,0.7)',
          fontSize: entry.emoji ? '1rem' : undefined,
          lineHeight: 1.6,
        }}
      >
        {entry.emoji ?? ICONS[entry.key]}
      </Box>
      <Box>
        <Typography
          variant="body2"
          sx={{ color: 'rgba(255,255,255,0.9)', fontWeight: 600 }}
        >
          {entry.label}
          {entry.smallScreenOnly && (
            <Typography
              component="span"
              variant="caption"
              sx={{ ml: 1, color: 'rgba(255,255,255,0.4)', fontWeight: 400 }}
            >
              small screens
            </Typography>
          )}
        </Typography>
        <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.6)' }}>
          {entry.description}
        </Typography>
      </Box>
    </Box>
  )
}

export default function IconGuideDialog({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullWidth
      maxWidth="sm"
      slotProps={{
        backdrop: { sx: { backgroundColor: 'rgba(0,0,0,0.3)' } },
      }}
    >
      <DialogTitle data-testid="icon-guide-title">
        Getting around CancerBot
      </DialogTitle>
      <DialogContent sx={{ pt: 1 }}>
        <Typography
          variant="body2"
          sx={{ color: 'rgba(255,255,255,0.6)', mb: 2 }}
        >
          A quick tour of the icons you'll see on this page.
        </Typography>

        {GUIDE_AREAS.map((area) => (
          <Box key={area} sx={{ mb: 2 }}>
            <Typography
              variant="caption"
              sx={{
                display: 'block',
                mb: 0.5,
                textTransform: 'uppercase',
                letterSpacing: 1,
                color: 'rgba(255,255,255,0.4)',
              }}
            >
              {area}
            </Typography>
            {entriesForArea(area).map((entry) => (
              <GuideRow key={entry.key} entry={entry} />
            ))}
          </Box>
        ))}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} variant="contained" data-testid="icon-guide-dismiss">
          Got it
        </Button>
      </DialogActions>
    </Dialog>
  )
}
