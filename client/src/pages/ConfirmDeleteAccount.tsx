import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { Box, Button, Stack, Typography, Alert, CircularProgress } from '@mui/material'

const AUTO_REDIRECT_MS = 8000

export default function ConfirmDeleteAccount() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const BASE_URL = import.meta.env.VITE_BASE_URL || ''

  const token = searchParams.get('token') ?? ''

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deletionDate, setDeletionDate] = useState<string | null>(null)

  useEffect(() => {
    if (!deletionDate) return
    const timer = setTimeout(() => navigate('/login'), AUTO_REDIRECT_MS)
    return () => clearTimeout(timer)
  }, [deletionDate, navigate])

  if (!token) {
    return (
      <Box sx={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Stack spacing={3} sx={{ maxWidth: 400, textAlign: 'center', p: 4 }}>
          <Typography variant="h5" fontWeight={600} color="error">Invalid link</Typography>
          <Typography sx={{ color: 'rgba(255,255,255,0.7)' }}>
            This deletion link is missing a token. Please request a new one from the app.
          </Typography>
          <Button variant="outlined" onClick={() => navigate('/login')}>Back to login</Button>
        </Stack>
      </Box>
    )
  }

  if (deletionDate) {
    return (
      <Box sx={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Stack spacing={3} sx={{ maxWidth: 420, textAlign: 'center', p: 4 }}>
          <Typography variant="h5" fontWeight={600}>Deletion scheduled</Typography>
          <Typography sx={{ color: 'rgba(255,255,255,0.7)' }}>
            Your account will be permanently deleted on{' '}
            {new Date(deletionDate).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })}.
            You can cancel any time before then just by logging in.
          </Typography>
          <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.5)' }}>
            Redirecting to login shortly…
          </Typography>
          <Button variant="contained" onClick={() => navigate('/login')}>Go to login now</Button>
        </Stack>
      </Box>
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const res = await fetch(`${BASE_URL}/auth/confirm-delete/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token }),
      })
      const data = await res.json().catch(() => null)
      if (res.ok) {
        setDeletionDate(data.deletion_date)
      } else {
        setError(data?.detail ?? 'Invalid or expired deletion link.')
      }
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', bgcolor: 'background.default' }}>
      <Stack spacing={3} sx={{ maxWidth: 400, width: '100%', p: 4 }}>
        <Typography variant="h5" fontWeight={600} textAlign="center">
          Confirm account deletion
        </Typography>
        <Typography sx={{ color: 'rgba(255,255,255,0.7)', textAlign: 'center' }}>
          Your account and conversations will be permanently deleted 7 days from now. You can cancel
          any time before then by logging in.
        </Typography>

        <Box component="form" onSubmit={handleSubmit}>
          <Stack spacing={2}>
            {error && <Alert severity="error">{error}</Alert>}
            <Button
              type="submit"
              variant="contained"
              color="error"
              fullWidth
              disabled={loading}
            >
              {loading ? <CircularProgress size={22} color="inherit" /> : 'Delete my account'}
            </Button>
          </Stack>
        </Box>

        <Button size="small" onClick={() => navigate('/login')} sx={{ alignSelf: 'center' }}>
          Back to login
        </Button>
      </Stack>
    </Box>
  )
}
