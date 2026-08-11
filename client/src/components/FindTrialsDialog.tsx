import { useState } from 'react'
import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import TravelExploreIcon from '@mui/icons-material/TravelExplore'
import { buildTrialSearchUrl, canSearchTrials } from '../utils/trialSearch'

/**
 * Opt-in "find trials I could join" flow. Collects a condition and a coarse
 * location, then opens ClinicalTrials.gov's own recruiting search.
 *
 * Nothing is prefilled from the conversation on purpose: guessing the user's
 * condition from chat text would be an assumption about their diagnosis, which
 * is exactly the wrong thing to get subtly wrong here.
 *
 * `variant`:
 *  - "icon"  — compact icon button for the sidebar header
 *  - "chip"  — inline chip for the new-conversation intro
 */
export default function FindTrialsDialog({
  variant = 'icon',
}: {
  variant?: 'icon' | 'chip'
}) {
  const [open, setOpen] = useState(false)
  const [condition, setCondition] = useState('')
  const [location, setLocation] = useState('')

  const handleClose = () => {
    setOpen(false)
    setCondition('')
    setLocation('')
  }

  const ready = canSearchTrials({ condition, location })

  const handleSearch = () => {
    if (!ready) return
    // Built and opened client-side — the condition/location never reach the
    // CancerBot backend and are never stored.
    window.open(
      buildTrialSearchUrl({ condition, location }),
      '_blank',
      'noopener,noreferrer',
    )
    handleClose()
  }

  const label = 'Find trials to join'

  const trigger =
    variant === 'chip' ? (
      <Chip
        icon={<TravelExploreIcon />}
        label={label}
        data-testid="find-trials-trigger"
        onClick={() => setOpen(true)}
        variant="outlined"
        sx={{
          cursor: 'pointer',
          color: 'rgba(255,255,255,0.85)',
          borderColor: 'rgba(255,255,255,0.25)',
          '&:hover': { borderColor: 'primary.main' },
        }}
      />
    ) : (
      <Tooltip title={label}>
        <IconButton
          size="small"
          aria-label={label}
          data-testid="find-trials-trigger"
          onClick={() => setOpen(true)}
          sx={{ color: 'rgba(255,255,255,0.6)' }}
        >
          <TravelExploreIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    )

  return (
    <>
      {trigger}

      <Dialog
        open={open}
        onClose={handleClose}
        fullWidth
        maxWidth="sm"
        slotProps={{
          backdrop: { sx: { backgroundColor: 'rgba(0,0,0,0.3)' } },
          paper: {
            sx: {
              backgroundColor: 'rgba(18,25,45,0.55)',
              backdropFilter: 'blur(18px)',
              boxShadow: '0 20px 60px rgba(0,0,0,0.4)',
              border: '1px solid rgba(255,255,255,0.1)',
            },
          },
        }}
      >
        <DialogTitle>Find clinical trials to join</DialogTitle>
        <DialogContent
          sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}
        >
          <Alert severity="info" data-testid="find-trials-disclaimer">
            This opens the official ClinicalTrials.gov search for trials that are
            currently recruiting. CancerBot does not screen eligibility or
            recommend trials — discuss any trial with your care team.
          </Alert>

          <TextField
            label="Condition"
            fullWidth
            value={condition}
            onChange={(e) => setCondition(e.target.value)}
            placeholder="e.g. glioblastoma, breast cancer"
            slotProps={{ htmlInput: { 'data-testid': 'find-trials-condition' } }}
          />
          <TextField
            label="Location"
            fullWidth
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="City and/or country, e.g. Tel Aviv, Israel"
            slotProps={{ htmlInput: { 'data-testid': 'find-trials-location' } }}
          />

          <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.5)' }}>
            A city or country is enough — no precise location is used. What you
            type here is sent only to ClinicalTrials.gov when you open the
            search; CancerBot does not store it.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose}>Cancel</Button>
          <Button
            onClick={handleSearch}
            variant="contained"
            disabled={!ready}
            data-testid="find-trials-submit"
          >
            Search ClinicalTrials.gov
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
