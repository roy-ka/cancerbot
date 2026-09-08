import { useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { Box, Button, Stack, TextField, Typography, Alert, CircularProgress } from '@mui/material'

export default function ChangeEmail() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const BASE_URL = import.meta.env.VITE_BASE_URL || ''

  const token = searchParams.get('token') ?? ''

  const [newEmail, setNewEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  if (!token) {
    return (
      <Box sx={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Stack spacing={3} sx={{ maxWidth: 400, textAlign: 'center', p: 4 }}>
          <Typography variant="h5" fontWeight={600} color="error">Invalid link</Typography>
          <Typography sx={{ color: 'rgba(255,255,255,0.7)' }}>
            This link is missing a token. Please request the email change again.
          </Typography>
          <Button variant="outlined" onClick={() => navigate('/login')}>Back to login</Button>
        </Stack>
      </Box>
    )
  }

  if (success) {
    return (
      <Box sx={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Stack spacing={3} sx={{ maxWidth: 400, textAlign: 'center', p: 4 }}>
          <Typography variant="h5" fontWeight={600}>Almost there!</Typography>
          <Typography sx={{ color: 'rgba(255,255,255,0.7)' }}>
            We've sent a confirmation link to {newEmail}. Open it there to finish the change.
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
      const res = await fetch(`${BASE_URL}/auth/change-email/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_email: newEmail, password }),
      })
      if (res.ok) {
        setSuccess(true)
      } else {
        const data = await res.json().catch(() => null)
        setError(data?.detail ?? 'Something went wrong. Please try again.')
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
          Choose your new email
        </Typography>

        <Box component="form" onSubmit={handleSubmit}>
          <Stack spacing={2}>
            <TextField
              fullWidth
              required
              label="New email"
              type="email"
              autoComplete="email"
              autoFocus
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
            />
            <TextField
              fullWidth
              required
              label="Current password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {error && <Alert severity="error">{error}</Alert>}
            <Button
              type="submit"
              variant="contained"
              fullWidth
              disabled={loading || !newEmail || !password}
            >
              {loading ? <CircularProgress size={22} color="inherit" /> : 'Continue'}
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
