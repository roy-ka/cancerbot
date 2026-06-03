import React, { useState, useMemo } from 'react'
import { Stack, TextField, FormControl, Button, Checkbox, FormControlLabel, Link, Box, Alert, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import type { RegistrationPayload } from '../types'

interface PasswordRequirement {
  label: string
  met: boolean
}

const PASSWORD_PATTERNS = {
  lowercase: /[a-z]/,
  uppercase: /[A-Z]/,
  digit: /[0-9]/,
  special: /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/,
}

function PasswordRequirements({ password }: { password: string }) {
  const requirements: PasswordRequirement[] = useMemo(
    () => [
      { label: 'At least 8 characters', met: password.length >= 8 },
      { label: 'Lowercase letters (a-z)', met: PASSWORD_PATTERNS.lowercase.test(password) },
      { label: 'Uppercase letters (A-Z)', met: PASSWORD_PATTERNS.uppercase.test(password) },
      { label: 'Numbers (0-9)', met: PASSWORD_PATTERNS.digit.test(password) },
      { label: 'Special characters (!@#$%^&*)', met: PASSWORD_PATTERNS.special.test(password) },
    ],
    [password]
  )

  return (
    <Box sx={{ mt: 1, p: 2, borderRadius: 1, bgcolor: 'rgba(255, 255, 255, 0.05)', border: '1px solid rgba(255, 255, 255, 0.1)' }}>
      <Typography variant="subtitle2" sx={{ mb: 1, color: 'rgba(255, 255, 255, 0.7)', fontSize: '0.85rem', fontWeight: 600 }}>
        Password Requirements
      </Typography>
      <Stack spacing={0.75}>
        {requirements.map((req) => (
          <Box
            key={req.label}
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              color: req.met ? 'rgba(47, 227, 198, 0.9)' : 'rgba(255, 255, 255, 0.5)',
              fontSize: '0.875rem',
              transition: 'color 0.2s ease',
            }}
          >
            <Box
              sx={{
                width: 16,
                height: 16,
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '0.7rem',
                fontWeight: 'bold',
                flexShrink: 0,
                ...(req.met
                  ? { bgcolor: 'rgba(47, 227, 198, 0.3)', color: 'rgba(47, 227, 198, 0.9)', border: '1px solid rgba(47, 227, 198, 0.6)' }
                  : { bgcolor: 'transparent', color: 'rgba(255, 255, 255, 0.4)', border: '1px solid rgba(255, 255, 255, 0.2)' }),
              }}
            >
              {req.met ? '✓' : '○'}
            </Box>
            {req.label}
          </Box>
        ))}
      </Stack>
    </Box>
  )
}

export default function RegistrationForm({
  changeToLogin,
}: {
  changeToLogin: () => void
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [emailError, setEmailError] = useState(false)
  const [passwordError, setPasswordError] = useState(false)
  const [name, setName] = useState('')
  const [termsAccepted, setTermsAccepted] = useState(false)
  const [error, setError] = useState('')
  const BASE_URL = import.meta.env.VITE_BASE_URL

  const verifyEmail = (email: string) => {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email === ''
  }

  const verifyPassword = (password: string) => {
    return password.length >= 8 || password === ''
  }

  const register = async (payload: RegistrationPayload) => {
    const res = await fetch(`${BASE_URL}/auth/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => null)
      throw new Error(err?.detail ?? err?.message ?? 'Registration failed')
    }
    console.log('Registration successful, redirecting to login...')
    changeToLogin()
  }

  const onSubmit = (e: React.SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (emailError || passwordError || !termsAccepted) {
      return
    }
    setError('')
    register({ email, password, name })
      .then((res) => {
        console.log('Registration successful:', res)
      })
      .catch((err) => {
        console.error('Registration error:', err)
        setError(err.message)
      })
  }

  const changeEmail = (e: React.ChangeEvent<HTMLInputElement>) => {
    const email = e.target.value
    setEmail(email)
    setEmailError(!verifyEmail(email))
  }

  const changePassword = (e: React.ChangeEvent<HTMLInputElement>) => {
    const password = e.target.value
    setPassword(password)
    setPasswordError(!verifyPassword(password))
  }
  const changeName = (e: React.ChangeEvent<HTMLInputElement>) => {
    const name = e.target.value
    setName(name)
  }

  return (
    <Stack spacing={2} sx={{ width: '100%' }}>
      {error && <Alert severity="error">{error}</Alert>}
      <FormControl component="form" onSubmit={onSubmit} sx={{ width: '100%' }}>
        <Stack spacing={2} sx={{ width: '100%' }}>
          <TextField
            fullWidth
            required
            id="name"
            name="name"
            label="Full name"
            type="name"
            autoComplete="name"
            variant="outlined"
            onChange={changeName}
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
            onChange={changeEmail}
            error={emailError}
          />

          <TextField
            fullWidth
            required
            id="password"
            name="password"
            label="Password"
            type="password"
            autoComplete="current-password"
            variant="outlined"
            onChange={changePassword}
            error={passwordError}
          />

          {password && <PasswordRequirements password={password} />}

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
            disabled={!termsAccepted}
          >
            Submit
          </Button>
        </Stack>
      </FormControl>
      <Button onClick={() => changeToLogin()}>
        Already have an account? Login
      </Button>
    </Stack>
  )
}
