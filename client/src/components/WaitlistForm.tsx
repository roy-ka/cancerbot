import { useState } from 'react'
import { Stack, TextField, FormControl, Button, Alert, Typography } from '@mui/material'
import type { WaitlistPayload } from '../types'

function WaitlistConfirmation({ email, onBackToLogin }: { email: string; onBackToLogin: () => void }) {
  return (
    <Stack spacing={3} sx={{ width: '100%', textAlign: 'center' }}>
      <Typography variant="h6" sx={{ fontWeight: 600 }}>You're on the list</Typography>
      <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.7)' }}>
        We'll email <strong>{email}</strong> an invite as soon as a spot opens up.
      </Typography>
      <Button variant="outlined" onClick={onBackToLogin}>Back to Login</Button>
    </Stack>
  )
}

export default function WaitlistForm({
  changeToLogin,
}: {
  changeToLogin: () => void
}) {
  const [email, setEmail] = useState('')
  const [emailError, setEmailError] = useState(false)
  const [error, setError] = useState('')
  const [joined, setJoined] = useState(false)
  const BASE_URL = import.meta.env.VITE_BASE_URL || ''

  const verifyEmail = (email: string) => {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email === ''
  }

  const join = async (payload: WaitlistPayload) => {
    const res = await fetch(`${BASE_URL}/auth/waitlist/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => null)
      throw new Error(err?.detail ?? err?.message ?? 'Could not join the waitlist')
    }
    setJoined(true)
  }

  const onSubmit = (e: React.SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (emailError || !email) return
    setError('')
    join({ email }).catch((err) => {
      console.error('Waitlist error:', err)
      setError(err.message)
    })
  }

  const changeEmail = (e: React.ChangeEvent<HTMLInputElement>) => {
    const email = e.target.value
    setEmail(email)
    setEmailError(!verifyEmail(email))
  }

  if (joined) {
    return <WaitlistConfirmation email={email} onBackToLogin={changeToLogin} />
  }

  return (
    <Stack spacing={2} sx={{ width: '100%' }}>
      <Alert severity="info">
        We've reached our current user limit — sorry! Leave your email and
        we'll send you an invitation once a spot opens up.
      </Alert>
      {error && <Alert severity="error">{error}</Alert>}
      <FormControl component="form" onSubmit={onSubmit} sx={{ width: '100%' }}>
        <Stack spacing={2} sx={{ width: '100%' }}>
          <TextField
            fullWidth
            required
            id="waitlist_email"
            name="email"
            label="Email"
            type="email"
            autoComplete="email"
            variant="outlined"
            onChange={changeEmail}
            error={emailError}
          />

          <Button type="submit" variant="contained" fullWidth disabled={!email || emailError}>
            Join the waitlist
          </Button>
        </Stack>
      </FormControl>
      <Button onClick={() => changeToLogin()}>
        Already have an account? Login
      </Button>
    </Stack>
  )
}
