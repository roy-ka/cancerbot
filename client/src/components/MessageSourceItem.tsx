import React, { useState } from 'react'
import {
  Box,
  Button,
  Chip,
  IconButton,
  Link,
  Popover,
  Tooltip,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import BiotechIcon from '@mui/icons-material/Biotech'
import type { Source } from '../types'
import { isTrialSource, trialBadgeLabel } from '../utils/trialBadge'

export default function MessageSourceItem({
  text,
  source,
  onAskAboutSource,
}: {
  text: string
  source: Source
  onAskAboutSource?: (sourceId: string) => void
}) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
  // Closing via "Ask about this source" moves focus to the message box, so
  // the popover must not hand focus back to the citation as it closes.
  const [askedAboutSource, setAskedAboutSource] = useState(false)
  const open = Boolean(anchorEl)
  const popupText = source.text
  const url = source.url ?? ''
  const name =
    !source.name || source.name === 'unknown'
      ? text
      : source.source_type === 'wikipedia'
        ? `wiki: ${source.name}`
        : source.name

  const handleClick = (e: React.MouseEvent<HTMLElement>) => {
    // Prevent navigating when later you swap to a link component.
    e.preventDefault()
    e.stopPropagation()
    setAskedAboutSource(false)
    setAnchorEl(e.currentTarget)
  }

  const handleClose = () => setAnchorEl(null)

  const chip = isTrialSource(source) ? (
    <Chip
      component="span"
      icon={<BiotechIcon />}
      label={trialBadgeLabel(source)}
      onClick={handleClick}
      size="small"
      sx={{
        cursor: 'pointer',
        fontWeight: 600,
        verticalAlign: 'baseline',
        color: 'secondary.main',
        borderColor: 'secondary.main',
        bgcolor: 'transparent',
        border: '1px solid',
        '& .MuiChip-icon': { color: 'secondary.main' },
      }}
      variant="outlined"
    />
  ) : (
    <Box
      component="span"
      onClick={handleClick}
      sx={{
        cursor: 'pointer',
        fontWeight: 600,
        color: 'primary.main',
      }}
    >
      {name}
    </Box>
  )

  return (
    <>
      {/* Hover popup */}
      <Tooltip
        title={
          <Box sx={{ maxWidth: 1000, p: 1 }}>
            <Typography variant="body1" sx={{ whiteSpace: 'pre-wrap' }}>
              {popupText || 'No details available.'}
            </Typography>
          </Box>
        }
        arrow
        enterDelay={250}
        slotProps={{
          tooltip: {
            sx: {
              opacity: 1,
              bgcolor: 'rgba(17, 24, 39, 0.98)',
              backdropFilter: 'none',
              maxWidth: '1000px',
              width: 'auto',
            },
          },
        }}
      >
        {chip}
      </Tooltip>

      {/* Click popup with close button */}
      <Popover
        open={open}
        anchorEl={anchorEl}
        onClose={handleClose}
        disableRestoreFocus={askedAboutSource}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        marginThreshold={12}
        slotProps={{
          paper: {
            sx: {
              width: { xs: 'calc(100vw - 24px)', sm: 'auto' },
              maxWidth: { xs: 'calc(100vw - 24px)', sm: 640 },
              p: 2,
              borderRadius: 2,
              bgcolor: 'rgba(17, 24, 39, 0.98)',
            },
          },
        }}
      >
        <Box sx={{ position: 'relative', maxWidth: 640 }}>
          {/* Close button top-right */}
          <IconButton
            size="small"
            onClick={handleClose}
            aria-label="Close"
            sx={{ position: 'absolute', top: 0, right: 0 }}
          >
            <CloseIcon fontSize="small" />
          </IconButton>

          <Box sx={{ pr: 4 }}>
            <Typography
              variant="body1"
              sx={{
                whiteSpace: 'pre-wrap',
                fontSize: '0.98rem',
                lineHeight: 1.7,
              }}
            >
              {popupText || 'No details available.'}
            </Typography>

            {/* Show source link ONLY in the click popup */}
            {url ? (
              <Box sx={{ mt: 2 }}>
                <Typography variant="caption">Source</Typography>
                <Box>
                  <Link
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    underline="hover"
                    sx={{ wordBreak: 'break-all' }}
                  >
                    {url}
                  </Link>
                </Box>
              </Box>
            ) : null}

            {onAskAboutSource && source.id ? (
              <Button
                size="small"
                variant="outlined"
                sx={{ mt: 2, textTransform: 'none' }}
                onClick={() => {
                  setAskedAboutSource(true)
                  setAnchorEl(null)
                  onAskAboutSource(source.id)
                }}
              >
                Ask about this source
              </Button>
            ) : null}
          </Box>
        </Box>
      </Popover>
    </>
  )
}
