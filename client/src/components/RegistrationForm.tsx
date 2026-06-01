import React, { useState } from 'react'
import { Stack, TextField, FormControl, Button, Checkbox, FormControlLabel, Link, Box, Alert } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import type { RegistrationPayload } from '../types'

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
    return password.length >= 6 || password === ''
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
