import { useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { Box, Button, Stack, TextField, Typography, Alert, CircularProgress } from '@mui/material'

export default function ResetPassword() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const BASE_URL = import.meta.env.VITE_BASE_URL || ''

  const token = searchParams.get('token') ?? ''

  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  if (!token) {
    return (
      <Box sx={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Stack spacing={3} sx={{ maxWidth: 400, textAlign: 'center', p: 4 }}>
          <Typography variant="h5" fontWeight={600} color="error">Invalid link</Typography>
          <Typography sx={{ color: 'rgba(255,255,255,0.7)' }}>
            This reset link is missing a token. Please request a new one.
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
          <Typography variant="h5" fontWeight={600}>Password updated!</Typography>
          <Typography sx={{ color: 'rgba(255,255,255,0.7)' }}>
            Your password has been reset. You can now log in.
          </Typography>
          <Button variant="contained" onClick={() => navigate('/login')}>Go to login</Button>
        </Stack>
      </Box>
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (newPassword !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setLoading(true)
    try {
      const res = await fetch(`${BASE_URL}/auth/reset-password/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: newPassword }),
      })
      if (res.ok) {
        setSuccess(true)
      } else {
        const data = await res.json().catch(() => null)
        setError(data?.detail ?? 'Invalid or expired reset link.')
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
          Choose a new password
        </Typography>

        <Box component="form" onSubmit={handleSubmit}>
          <Stack spacing={2}>
            <TextField
              fullWidth
              required
              label="New password"
              type="password"
              autoComplete="new-password"
              autoFocus
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
            <TextField
              fullWidth
              required
              label="Confirm password"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
            {error && <Alert severity="error">{error}</Alert>}
            <Button
              type="submit"
              variant="contained"
              fullWidth
              disabled={loading || !newPassword || !confirmPassword}
            >
              {loading ? <CircularProgress size={22} color="inherit" /> : 'Reset password'}
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
