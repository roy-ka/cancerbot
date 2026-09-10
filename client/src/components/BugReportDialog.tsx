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
  ToggleButtonGroup,
  ToggleButton,
} from '@mui/material'
import FeedbackOutlinedIcon from '@mui/icons-material/FeedbackOutlined'

type ReportType = 'bug' | 'feedback'

export default function BugReportDialog({ compact = false }: { compact?: boolean }) {
  const [open, setOpen] = useState(false)
  const [reportType, setReportType] = useState<ReportType>('bug')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [howToReproduce, setHowToReproduce] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState('')

  const BASE_URL = import.meta.env.VITE_BASE_URL || ''

  const handleClose = () => {
    setOpen(false)
    setReportType('bug')
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
        body: JSON.stringify({
          title,
          description,
          how_to_reproduce: reportType === 'bug' ? howToReproduce : undefined,
          report_type: reportType,
        }),
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
    <Tooltip title="Report a bug or send feedback">
      <IconButton size="small" onClick={() => setOpen(true)} sx={{ color: 'rgba(255,255,255,0.6)' }}>
        <FeedbackOutlinedIcon fontSize="small" />
      </IconButton>
    </Tooltip>
  ) : (
    <Button
      size="small"
      startIcon={<FeedbackOutlinedIcon />}
      onClick={() => setOpen(true)}
      sx={{ textTransform: 'none', opacity: 0.7 }}
    >
      Feedback
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
        }}
      >
        <DialogTitle>{reportType === 'bug' ? 'Report a Bug' : 'Send Feedback'}</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {success && <Alert severity="success">Thank you! Your {reportType === 'bug' ? 'report' : 'feedback'} was submitted.</Alert>}
          {error && <Alert severity="error">{error}</Alert>}
          <ToggleButtonGroup
            value={reportType}
            exclusive
            onChange={(_, value: ReportType | null) => value && setReportType(value)}
            size="small"
            fullWidth
          >
            <ToggleButton value="bug">Bug</ToggleButton>
            <ToggleButton value="feedback">Feedback</ToggleButton>
          </ToggleButtonGroup>
          <TextField
            label="Title"
            required
            fullWidth
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={reportType === 'bug' ? 'Short summary of the issue' : 'Short summary of your feedback'}
          />
          <TextField
            label={reportType === 'bug' ? 'Description' : 'Your feedback'}
            fullWidth
            multiline
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={reportType === 'bug' ? 'What went wrong?' : 'What do you think about CancerBot? Ideas, suggestions, anything on your mind.'}
          />
          {reportType === 'bug' && (
            <TextField
              label="How to reproduce"
              fullWidth
              multiline
              rows={3}
              value={howToReproduce}
              onChange={(e) => setHowToReproduce(e.target.value)}
              placeholder="Steps to reproduce the issue"
            />
          )}
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
