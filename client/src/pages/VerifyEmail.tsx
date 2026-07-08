import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { Box, CircularProgress, Typography, Button, Stack } from '@mui/material'

export default function VerifyEmail() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading')
  const [message, setMessage] = useState('')
  const BASE_URL = import.meta.env.VITE_BASE_URL || ''

  useEffect(() => {
    if (status !== 'loading') return

    const token = searchParams.get('token')
    if (!token) {
      setStatus('error')
      setMessage('No verification token found in the link.')
      return
    }

    fetch(`${BASE_URL}/auth/verify-email/?token=${encodeURIComponent(token)}`)
      .then(async (res) => {
        const data = await res.json().catch(() => null)
        if (res.ok) {
          if (data?.already_verified) {
            navigate('/login?verified=1')
            return
          }
          setStatus('success')
          setMessage(data?.message ?? 'Email verified successfully.')
        } else {
          setStatus('error')
          setMessage(data?.detail ?? 'Verification failed.')
        }
      })
      .catch(() => {
        setStatus('error')
        setMessage('Network error. Please try again.')
      })
  }, [searchParams])

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        bgcolor: 'background.default',
      }}
    >
      <Stack spacing={3} sx={{ maxWidth: 400, textAlign: 'center', p: 4 }}>
        {status === 'loading' && (
          <>
            <CircularProgress sx={{ mx: 'auto' }} />
            <Typography>Verifying your email…</Typography>
          </>
        )}

        {status === 'success' && (
          <>
            <Typography variant="h5" fontWeight={600}>Email verified!</Typography>
            <Typography sx={{ color: 'rgba(255,255,255,0.7)' }}>{message}</Typography>
            <Button variant="contained" onClick={() => navigate('/login')}>Go to Login</Button>
          </>
        )}

        {status === 'error' && (
          <>
            <Typography variant="h5" fontWeight={600} color="error">Verification failed</Typography>
            <Typography sx={{ color: 'rgba(255,255,255,0.7)' }}>{message}</Typography>
            <Button variant="outlined" onClick={() => navigate('/login')}>Back to Login</Button>
          </>
        )}
      </Stack>
    </Box>
  )
}
