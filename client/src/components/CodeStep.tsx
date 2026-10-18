import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Link,
  Stack,
  Typography,
} from '@mui/material'
import { useNavigate } from 'react-router-dom'
import CodeInput, { CODE_LENGTH } from './CodeInput'

const RESEND_COOLDOWN_SECONDS = 30

type CodeStepProps = {
  email: string
  rememberMe: boolean
  // Only present when the backend runs with DEV_EMAIL_SHORTCUTS (never in
  // production) — shown so local development needs no inbox.
  devCode?: string
  onBack: () => void
}

/**
 * Second step of both sign-in and registration: enter the 6-digit code
 * that was emailed to `email`. A correct code sets the session cookie and
 * goes to the app (or the ninja console); a scheduled account deletion
 * opens a dialog offering to cancel it instead.
 */
export default function CodeStep({ email, rememberMe, devCode: initialDevCode, onBack }: CodeStepProps) {
  const BASE_URL = import.meta.env.VITE_BASE_URL || ''
  const navigate = useNavigate()
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [verifying, setVerifying] = useState(false)
  const [cooldown, setCooldown] = useState(RESEND_COOLDOWN_SECONDS)
  const [devCode, setDevCode] = useState(initialDevCode)
  const [pendingDeletion, setPendingDeletion] = useState<{ deletionDate: string; cancelToken: string } | null>(null)
  const [cancelling, setCancelling] = useState(false)

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = setTimeout(() => setCooldown((c) => c - 1), 1000)
    return () => clearTimeout(timer)
  }, [cooldown])

  const verify = async (digits: string) => {
    if (digits.length !== CODE_LENGTH || verifying) return
    setVerifying(true)
    setError('')
    setInfo('')
    try {
      const res = await fetch(`${BASE_URL}/auth/verify-code/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, code: digits, rememberMe }),
        credentials: 'include',
      })
      const data = await res.json().catch(() => null)
      if (res.ok) {
        navigate(data?.is_ninja ? '/ninja' : '/chat')
        return
      }
      const detail = data?.detail
      if (detail && typeof detail === 'object' && detail.code === 'pending_deletion') {
        setPendingDeletion({ deletionDate: detail.deletion_date, cancelToken: detail.cancel_token })
        return
      }
      setError(typeof detail === 'string' ? detail : 'That code did not work. Please try again.')
      setCode('')
    } catch {
      setError('Something went wrong. Please try again.')
      setCode('')
    } finally {
      setVerifying(false)
    }
  }

  const resend = async () => {
    setError('')
    setInfo('')
    setCode('')
    try {
      const res = await fetch(`${BASE_URL}/auth/request-code/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      const data = await res.json().catch(() => null)
      if (!res.ok) {
        setError(typeof data?.detail === 'string' ? data.detail : 'Could not send a new code.')
        return
      }
      setDevCode(data?.dev_code)
      setInfo('We sent you a new code.')
      setCooldown(RESEND_COOLDOWN_SECONDS)
    } catch {
      setError('Something went wrong. Please try again.')
    }
  }

  const cancelDeletion = async () => {
    if (!pendingDeletion) return
    setCancelling(true)
    try {
      const res = await fetch(`${BASE_URL}/auth/cancel-delete/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cancel_token: pendingDeletion.cancelToken }),
        credentials: 'include',
      })
      if (res.ok) {
        navigate('/chat')
        return
      }
      const data = await res.json().catch(() => null)
      setPendingDeletion(null)
      setCode('')
      setError(
        typeof data?.detail === 'string'
          ? data.detail
          : 'This cancellation link has expired. Please request a new code.'
      )
    } finally {
      setCancelling(false)
    }
  }

  // The code that produced the dialog is already spent; clear it so the
  // boxes don't show a code that can no longer be used.
  const dismissPendingDeletion = () => {
    setPendingDeletion(null)
    setCode('')
  }

  return (
    <Stack spacing={2.5} sx={{ width: '100%' }}>
      <Stack spacing={0.75} sx={{ textAlign: 'center' }}>
        <Typography variant="h6" sx={{ fontWeight: 700 }}>Check your email</Typography>
        <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.7)' }}>
          We sent a 6-digit code to <strong>{email}</strong>. It expires in 10 minutes.
        </Typography>
      </Stack>

      {devCode && (
        <Alert severity="info" data-testid="dev-code">
          Development mode — your code is <strong>{devCode}</strong>
        </Alert>
      )}

      <CodeInput
        value={code}
        onChange={(v) => {
          setCode(v)
          if (error) setError('')
        }}
        onComplete={verify}
        disabled={verifying}
        error={Boolean(error)}
        autoFocus
      />

      {error && <Alert severity="error">{error}</Alert>}
      {info && !error && <Alert severity="success">{info}</Alert>}

      <Button
        variant="contained"
        fullWidth
        disabled={verifying || code.length !== CODE_LENGTH}
        onClick={() => verify(code)}
      >
        {verifying ? <CircularProgress size={22} color="inherit" /> : 'Continue'}
      </Button>

      <Typography variant="body2" sx={{ textAlign: 'center', color: 'rgba(255,255,255,0.6)' }}>
        Didn't get it? Check your spam folder or{' '}
        {cooldown > 0 ? (
          <span>resend in {cooldown}s</span>
        ) : (
          <Link component="button" type="button" onClick={resend} sx={{ verticalAlign: 'baseline' }}>
            resend the code
          </Link>
        )}
        .
      </Typography>

      <Button size="small" onClick={onBack}>
        Use a different email
      </Button>

      <Dialog
        open={Boolean(pendingDeletion)}
        onClose={dismissPendingDeletion}
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
          <Button onClick={dismissPendingDeletion} disabled={cancelling}>
            Not now
          </Button>
          <Button onClick={cancelDeletion} variant="contained" disabled={cancelling}>
            {cancelling ? 'Cancelling…' : 'Cancel deletion'}
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}
