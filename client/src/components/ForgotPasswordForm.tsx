import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Stack, TextField, FormControl, Button, Typography, Alert } from '@mui/material'

export default function ForgotPasswordForm({ onBack }: { onBack: () => void }) {
  const BASE_URL = import.meta.env.VITE_BASE_URL || ''
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const res = await fetch(`${BASE_URL}/auth/forgot-password/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      const data = await res.json().catch(() => null)
      // reset_token is only ever returned when the backend runs with
      // DEV_EMAIL_SHORTCUTS — skip the email and go straight to the reset page.
      if (data?.reset_token) {
        navigate(`/reset-password?token=${encodeURIComponent(data.reset_token)}`)
        return
      }
      setSent(true)
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (sent) {
    return (
      <Stack spacing={2} sx={{ width: '100%' }}>
        <Alert severity="success">
          If that email is registered, you'll receive a reset link shortly.
          Check your inbox and click the link to set a new password.
        </Alert>
        <Button variant="contained" fullWidth onClick={onBack}>
          Back to login
        </Button>
      </Stack>
    )
  }

  return (
    <Stack spacing={2} sx={{ width: '100%' }}>
      <FormControl component="form" onSubmit={handleSubmit} sx={{ width: '100%' }}>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            Enter your email and we'll send you a reset link.
          </Typography>
          <TextField
            fullWidth
            required
            label="Email"
            type="email"
            autoComplete="email"
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          {error && <Alert severity="error">{error}</Alert>}
          <Button type="submit" variant="contained" fullWidth disabled={loading}>
            {loading ? 'Sending…' : 'Send reset link'}
          </Button>
        </Stack>
      </FormControl>
      <Button size="small" onClick={onBack}>
        Back to login
      </Button>
    </Stack>
  )
}
