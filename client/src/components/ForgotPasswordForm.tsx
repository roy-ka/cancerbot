import React, { useRef, useState } from 'react'
import {
  Stack,
  TextField,
  FormControl,
  Button,
  Typography,
  Alert,
} from '@mui/material'

type Step = 'email' | 'code'

export default function ForgotPasswordForm({
  onBack,
}: {
  onBack: () => void
}) {
  const BASE_URL = import.meta.env.VITE_BASE_URL || ''
  const [step, setStep] = useState<Step>('email')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)
  const codeRef = useRef<HTMLInputElement>(null)

  const handleRequestCode = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await fetch(`${BASE_URL}/auth/forgot-password/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      // Always advance — don't leak whether email exists
      setStep('code')
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (newPassword.length < 6) {
      setError('Password must be at least 6 characters.')
      return
    }
    setLoading(true)
    try {
      const res = await fetch(`${BASE_URL}/auth/reset-password/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, code, new_password: newPassword }),
      })
      if (res.ok) {
        setSuccess(true)
      } else {
        const data = await res.json().catch(() => null)
        setError(data?.detail ?? 'Invalid or expired code.')
      }
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <Stack spacing={2} sx={{ width: '100%' }}>
        <Alert severity="success">
          Password updated successfully. You can now log in.
        </Alert>
        <Button variant="contained" fullWidth onClick={onBack}>
          Back to login
        </Button>
      </Stack>
    )
  }

  return (
    <Stack spacing={2} sx={{ width: '100%' }}>
      {step === 'email' ? (
        <FormControl
          component="form"
          onSubmit={handleRequestCode}
          sx={{ width: '100%' }}
        >
          <Stack spacing={2}>
            <Typography variant="body2" color="text.secondary">
              Enter your email and we'll send you a 6-digit code.
            </Typography>
            <TextField
              fullWidth
              required
              label="Email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            {error && <Alert severity="error">{error}</Alert>}
            <Button
              type="submit"
              variant="contained"
              fullWidth
              disabled={loading}
            >
              {loading ? 'Sending…' : 'Send code'}
            </Button>
          </Stack>
        </FormControl>
      ) : (
        <FormControl
          component="form"
          onSubmit={handleResetPassword}
          sx={{ width: '100%' }}
        >
          <Stack spacing={2}>
            <Typography variant="body2" color="text.secondary">
              Enter the 6-digit code sent to <strong>{email}</strong> and
              choose a new password.
            </Typography>
            <TextField
              fullWidth
              required
              label="6-digit code"
              inputRef={codeRef}
              inputProps={{ maxLength: 6, inputMode: 'numeric', pattern: '[0-9]{6}' }}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              autoFocus
            />
            <TextField
              fullWidth
              required
              label="New password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
            {error && <Alert severity="error">{error}</Alert>}
            <Button
              type="submit"
              variant="contained"
              fullWidth
              disabled={loading || code.length !== 6}
            >
              {loading ? 'Resetting…' : 'Reset password'}
            </Button>
            <Button
              size="small"
              onClick={() => { setStep('email'); setCode(''); setError(null) }}
            >
              Resend code
            </Button>
          </Stack>
        </FormControl>
      )}
      <Button size="small" onClick={onBack}>
        Back to login
      </Button>
    </Stack>
  )
}
