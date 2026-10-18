import React, { useState } from 'react'
import { Stack, TextField, FormControl, Button, Checkbox, FormControlLabel, Link, Box, Alert, CircularProgress } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import type { RegistrationPayload } from '../types'
import CodeStep from './CodeStep'

export default function RegistrationForm({ changeToLogin }: { changeToLogin: () => void }) {
  const [email, setEmail] = useState('')
  const [emailError, setEmailError] = useState(false)
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [termsAccepted, setTermsAccepted] = useState(false)
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const [codeSent, setCodeSent] = useState(false)
  const [devCode, setDevCode] = useState<string | undefined>()
  const BASE_URL = import.meta.env.VITE_BASE_URL || ''

  const verifyEmail = (email: string) => {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email === ''
  }

  const register = async (payload: RegistrationPayload) => {
    const res = await fetch(`${BASE_URL}/auth/register/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify(payload),
    })
    const data = await res.json().catch(() => null)
    if (!res.ok) {
      throw new Error(typeof data?.detail === 'string' ? data.detail : 'Registration failed')
    }
    // The backend lowercases addresses; verify against the same spelling.
    setEmail(data?.email ?? payload.email)
    setDevCode(data?.dev_code)
    setCodeSent(true)
  }

  const onSubmit = (e: React.SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (emailError || !termsAccepted) {
      return
    }
    setError('')
    setSending(true)
    register({ email, first_name: firstName, last_name: lastName })
      .catch((err) => {
        console.error('Registration error:', err)
        setError(err.message)
      })
      .finally(() => setSending(false))
  }

  const changeEmail = (e: React.ChangeEvent<HTMLInputElement>) => {
    const email = e.target.value
    setEmail(email)
    setEmailError(!verifyEmail(email))
  }

  if (codeSent) {
    // Registration always starts a fresh session; there's no "remember me"
    // choice on this form, so the session lasts until the browser closes.
    return (
      <CodeStep
        email={email}
        rememberMe={false}
        devCode={devCode}
        onBack={() => setCodeSent(false)}
      />
    )
  }

  return (
    <Stack spacing={2} sx={{ width: '100%' }}>
      {error && <Alert severity="error">{error}</Alert>}
      <FormControl component="form" onSubmit={onSubmit} sx={{ width: '100%' }}>
        <Stack spacing={2} sx={{ width: '100%' }}>
          <TextField
            fullWidth
            required
            id="first_name"
            name="first_name"
            label="First name"
            autoComplete="given-name"
            variant="outlined"
            value={firstName}
            onChange={(e) => setFirstName(e.target.value)}
          />

          <TextField
            fullWidth
            required
            id="last_name"
            name="last_name"
            label="Last name"
            autoComplete="family-name"
            variant="outlined"
            value={lastName}
            onChange={(e) => setLastName(e.target.value)}
          />

          <TextField
            fullWidth
            required
            id="email"
            name="email"
            label="Email"
            type="email"
            autoComplete="email"
            variant="outlined"
            value={email}
            onChange={changeEmail}
            error={emailError}
            helperText="We'll email you a 6-digit code to finish signing up."
          />

          <Box>
            <FormControlLabel
              control={
                <Checkbox
                  checked={termsAccepted}
                  onChange={(e) => setTermsAccepted(e.target.checked)}
                  required
                />
              }
              label={
                <Box component="span">
                  I accept the{' '}
                  <Link
                    component={RouterLink}
                    to="/terms?readonly=true"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Terms and Conditions
                  </Link>
                </Box>
              }
            />
          </Box>

          <Button
            type="submit"
            variant="contained"
            fullWidth
            disabled={sending || !termsAccepted}
          >
            {sending ? <CircularProgress size={22} color="inherit" /> : 'Create account'}
          </Button>
        </Stack>
      </FormControl>
      <Button onClick={() => changeToLogin()}>
        Already have an account? Login
      </Button>
    </Stack>
  )
}
