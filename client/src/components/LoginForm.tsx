import { Stack, TextField, FormControl, Button, FormControlLabel, Checkbox, Alert, CircularProgress } from '@mui/material'
import React, { useState } from 'react'
import CodeStep from './CodeStep'

export default function LoginForm() {
  const [email, setEmail] = useState('')
  const [rememberMe, setRememberMe] = useState(false)
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const [codeSent, setCodeSent] = useState(false)
  const [devCode, setDevCode] = useState<string | undefined>()
  const BASE_URL = import.meta.env.VITE_BASE_URL || ''

  const onSubmit = async (e: React.SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError('')
    setSending(true)
    try {
      const res = await fetch(`${BASE_URL}/auth/request-code/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      const data = await res.json().catch(() => null)
      if (!res.ok) {
        const detail = data?.detail
        setError(typeof detail === 'string' ? detail : 'Could not send a code. Please check the email address.')
        return
      }
      // The backend lowercases addresses; verify against the same spelling.
      setEmail(data?.email ?? email)
      setDevCode(data?.dev_code)
      setCodeSent(true)
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setSending(false)
    }
  }

  if (codeSent) {
    return (
      <CodeStep
        email={email}
        rememberMe={rememberMe}
        devCode={devCode}
        onBack={() => setCodeSent(false)}
      />
    )
  }

  return (
    <FormControl component="form" onSubmit={onSubmit} sx={{ width: '100%' }}>
      <Stack spacing={2} sx={{ width: '100%' }}>
        {error && (
          <Alert severity="error" onClose={() => setError('')}>
            {error}
          </Alert>
        )}
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
          onChange={(e) => setEmail(e.target.value)}
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={rememberMe}
              onChange={(e) => setRememberMe(e.target.checked)}
            />
          }
          label="Remember me"
        />
        <Button type="submit" variant="contained" fullWidth disabled={sending || !email}>
          {sending ? <CircularProgress size={22} color="inherit" /> : 'Email me a code'}
        </Button>
      </Stack>
    </FormControl>
  )
}
