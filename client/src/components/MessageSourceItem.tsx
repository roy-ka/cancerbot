import React, { useState } from 'react'
import {
  Box,
  Button,
  Divider,
  IconButton,
  Link,
  Popover,
  Tooltip,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import AddCommentOutlinedIcon from '@mui/icons-material/AddCommentOutlined'
import type { SourceAndClaim } from '../types'

export default function MessageSourceItem({
  source,
  onInsertReference,
}: {
  source: SourceAndClaim
  onInsertReference?: (id: string) => void
}) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
  const open = Boolean(anchorEl)
  const popupText = source.text
  const url = source.url ?? ''

  // Display label: prefer title, then domain name, then cleaned id
  const displayName =
    source.title?.trim() ||
    (source.name && source.name !== 'unknown' ? source.name : null) ||
    source.id.replace(/^(pmid|doi|url|src):/, '')

  const handleClick = (e: React.MouseEvent<HTMLElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setAnchorEl(e.currentTarget)
  }

  const handleClose = () => setAnchorEl(null)

  const handleAddToAnswer = () => {
    onInsertReference?.(source.id)
    handleClose()
  }

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
      {displayName}
    </Box>
  )

  return (
    <>
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

      <Popover
        open={open}
        anchorEl={anchorEl}
        onClose={handleClose}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        slotProps={{
          paper: {
            sx: {
              maxWidth: 640,
              p: 2,
              borderRadius: 2,
              bgcolor: 'rgba(17, 24, 39, 0.98)',
            },
          },
        }}
      >
        <Box sx={{ position: 'relative', maxWidth: 640 }}>
          <IconButton
            size="small"
            onClick={handleClose}
            aria-label="Close"
            sx={{ position: 'absolute', top: 0, right: 0 }}
          >
            <CloseIcon fontSize="small" />
          </IconButton>

          <Box sx={{ pr: 4 }}>
            {source.title && (
              <Typography
                variant="subtitle2"
                sx={{ mb: 1, fontWeight: 700, color: 'primary.light' }}
              >
                {source.title}
              </Typography>
            )}

            <Typography
              variant="body1"
              sx={{ whiteSpace: 'pre-wrap', fontSize: '0.98rem', lineHeight: 1.7 }}
            >
              {popupText || 'No details available.'}
            </Typography>

            {url && (
              <Box sx={{ mt: 2 }}>
                <Typography variant="caption">Source</Typography>
                <Box>
                  <Link href={url} target="_blank" rel="noopener noreferrer" underline="hover">
                    {source.title || displayName}
                  </Link>
                </Box>
              </Box>
            )}

            <Divider sx={{ my: 1.5, borderColor: 'rgba(255,255,255,0.12)' }} />

            <Button
              size="small"
              startIcon={<AddCommentOutlinedIcon fontSize="small" />}
              onClick={handleAddToAnswer}
              variant="outlined"
              sx={{ textTransform: 'none' }}
            >
              Add to answer
            </Button>
          </Box>
        </Box>
      </Popover>
    </>
  )
}
