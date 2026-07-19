import { useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { Box, Button, Stack, TextField, Typography, Alert, CircularProgress } from '@mui/material'

export default function ConfirmDeleteAccount() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const BASE_URL = import.meta.env.VITE_BASE_URL || ''

  const token = searchParams.get('token') ?? ''

  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deletionDate, setDeletionDate] = useState<string | null>(null)

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
          <Button variant="contained" onClick={() => navigate('/login')}>Go to login</Button>
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
        body: JSON.stringify({ token, password }),
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
          Enter your password to schedule deletion. Your account and conversations will be permanently
          deleted 7 days from now.
        </Typography>

        <Box component="form" onSubmit={handleSubmit}>
          <Stack spacing={2}>
            <TextField
              fullWidth
              required
              label="Password"
              type="password"
              autoComplete="current-password"
              autoFocus
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {error && <Alert severity="error">{error}</Alert>}
            <Button
              type="submit"
              variant="contained"
              color="error"
              fullWidth
              disabled={loading || !password}
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
