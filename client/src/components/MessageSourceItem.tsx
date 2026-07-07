import React, { useState } from 'react'
import {
  Box,
  IconButton,
  Link,
  Popover,
  Tooltip,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import type { Source } from '../types'

export default function MessageSourceItem({
  text,
  source,
}: {
  text: string
  source: Source
}) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
  const open = Boolean(anchorEl)
  const popupText = source.text
  const url = source.url ?? ''
  const name =
    source.name === 'unknown'
      ? text
      : source.source_type === 'wikipedia'
        ? `wiki: ${source.name}`
        : source.name

  const handleClick = (e: React.MouseEvent<HTMLElement>) => {
    // Prevent navigating when later you swap to a link component.
    e.preventDefault()
    e.stopPropagation()
    setAnchorEl(e.currentTarget)
  }

  const handleClose = () => setAnchorEl(null)

  const chip = (
    <Box
      component="span"
      onClick={handleClick}
      sx={{
        cursor: 'pointer',
        fontWeight: 600,
        color: 'primary.main',
        userSelect: 'none',
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
                  >
                    {name}
                  </Link>
                </Box>
              </Box>
            ) : null}
          </Box>
        </Box>
      </Popover>
    </>
  )
}
