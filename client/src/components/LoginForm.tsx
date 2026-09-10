import {
  Stack,
  TextField,
  FormControl,
  Button,
  FormControlLabel,
  Checkbox,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@mui/material'
import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { LoginPayload } from '../types'

export default function LoginForm({
  onForgotPassword,
}: {
  onForgotPassword?: () => void
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [rememberMe, setRememberMe] = useState(false)
  const [error, setError] = useState('')
  const [pendingDeletion, setPendingDeletion] = useState<{ deletionDate: string; cancelToken: string } | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const navigate = useNavigate()

  const login = async (payload: LoginPayload) => {
    const BASE_URL = import.meta.env.VITE_BASE_URL || ''

    const res = await fetch(`${BASE_URL}/auth/login/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      credentials: 'include',
    })
    if (res.ok) {
      setError('')
      const data = await res.json().catch(() => null)
      navigate(data?.is_ninja ? '/ninja' : '/chat')
    } else {
      const err = await res.json()
      const detail = err?.detail
      if (detail && typeof detail === 'object' && detail.code === 'pending_deletion') {
        setPendingDeletion({ deletionDate: detail.deletion_date, cancelToken: detail.cancel_token })
        return
      }
      const errorMessage = typeof detail === 'string' ? detail : 'Login failed'
      setError(errorMessage)
      if (res.status === 429) {
        console.error('Account locked:', errorMessage)
      }
      throw new Error(errorMessage)
    }
  }

  const handleCancelDeletion = async () => {
    if (!pendingDeletion) return
    const BASE_URL = import.meta.env.VITE_BASE_URL || ''
    setCancelling(true)
    try {
      const res = await fetch(`${BASE_URL}/auth/cancel-delete/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cancel_token: pendingDeletion.cancelToken }),
      })
      if (res.ok) {
        setPendingDeletion(null)
        setError('')
        login({ email, password, rememberMe }).catch(() => {
          setError('Deletion cancelled, but automatic login failed. Please log in again.')
        })
      } else {
        const err = await res.json().catch(() => null)
        setPendingDeletion(null)
        setError(typeof err?.detail === 'string' ? err.detail : 'This cancellation link has expired. Please log in again to get a new one.')
      }
    } finally {
      setCancelling(false)
    }
  }

  const onSubmit = (e: React.SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    login({ email, password, rememberMe }).catch(() => {})
  }
  const changeEmail = (e: React.ChangeEvent<HTMLInputElement>) => {
    const email = e.target.value
    setEmail(email)
  }

  const changePassword = (e: React.ChangeEvent<HTMLInputElement>) => {
    const password = e.target.value
    setPassword(password)
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
          onChange={changeEmail}
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
        <Button type="submit" variant="contained" fullWidth>
          Submit
        </Button>
        {onForgotPassword && (
          <Button size="small" onClick={onForgotPassword}>
            Forgot password?
          </Button>
        )}
      </Stack>

      <Dialog
        open={Boolean(pendingDeletion)}
        onClose={() => setPendingDeletion(null)}
        slotProps={{
          backdrop: { sx: { backgroundColor: 'rgba(0,0,0,0.3)' } },
        }}
      >
        <DialogTitle sx={{ color: 'rgba(255,255,255,0.92)' }}>Account scheduled for deletion</DialogTitle>
        <DialogContent sx={{ color: 'rgba(255,255,255,0.66)' }}>
          Your account leaves us on{' '}
          {pendingDeletion &&
            new Date(pendingDeletion.deletionDate).toLocaleDateString(undefined, {
              year: 'numeric',
              month: 'long',
              day: 'numeric',
            })}
          . The umbrella is folded, the little book is closed. One click can fix all of this — cancel deletion?
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2, gap: 1 }}>
          <Button onClick={() => setPendingDeletion(null)} disabled={cancelling}>
            Not now
          </Button>
          <Button onClick={handleCancelDeletion} variant="contained" disabled={cancelling}>
            {cancelling ? 'Cancelling…' : 'Cancel deletion'}
          </Button>
        </DialogActions>
      </Dialog>
    </FormControl>
  )
}
