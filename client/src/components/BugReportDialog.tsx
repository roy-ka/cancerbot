import { useState } from 'react'
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  TextField,
  Tooltip,
  Alert,
} from '@mui/material'
import BugReportIcon from '@mui/icons-material/BugReport'

export default function BugReportDialog({ compact = false }: { compact?: boolean }) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [howToReproduce, setHowToReproduce] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState('')

  const BASE_URL = import.meta.env.VITE_BASE_URL || ''

  const handleClose = () => {
    setOpen(false)
    setTitle('')
    setDescription('')
    setHowToReproduce('')
    setError('')
    setSuccess(false)
  }

  const handleSubmit = async () => {
    if (!title.trim()) {
      setError('Title is required')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const res = await fetch(`${BASE_URL}/bug-reports/`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, description, how_to_reproduce: howToReproduce }),
      })
      if (!res.ok) throw new Error(await res.text())
      setSuccess(true)
      setTimeout(handleClose, 1500)
    } catch {
      setError('Failed to submit. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const trigger = compact ? (
    <Tooltip title="Report a bug">
      <IconButton size="small" onClick={() => setOpen(true)} sx={{ color: 'rgba(255,255,255,0.6)' }}>
        <BugReportIcon fontSize="small" />
      </IconButton>
    </Tooltip>
  ) : (
    <Button
      size="small"
      startIcon={<BugReportIcon />}
      onClick={() => setOpen(true)}
      sx={{ textTransform: 'none', opacity: 0.7 }}
    >
      Report a bug
    </Button>
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
          paper: { sx: { backgroundColor: 'rgba(18,25,45,0.55)', backdropFilter: 'blur(18px)', boxShadow: '0 20px 60px rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.1)' } },
        }}
      >
        <DialogTitle>Report a Bug</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {success && <Alert severity="success">Thank you! Your report was submitted.</Alert>}
          {error && <Alert severity="error">{error}</Alert>}
          <TextField
            label="Title"
            required
            fullWidth
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Short summary of the issue"
          />
          <TextField
            label="Description"
            fullWidth
            multiline
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What went wrong?"
          />
          <TextField
            label="How to reproduce"
            fullWidth
            multiline
            rows={3}
            value={howToReproduce}
            onChange={(e) => setHowToReproduce(e.target.value)}
            placeholder="Steps to reproduce the issue"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} disabled={submitting}>Cancel</Button>
          <Button onClick={handleSubmit} variant="contained" disabled={submitting}>
            {submitting ? 'Submitting…' : 'Submit'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
