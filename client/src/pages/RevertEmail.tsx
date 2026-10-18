import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { Box, CircularProgress, Typography, Button, Stack } from '@mui/material'

export default function RevertEmail() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token')
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>(
    token ? 'loading' : 'error',
  )
  const [message, setMessage] = useState(
    token ? '' : 'No revert token found in the link.',
  )
  const BASE_URL = import.meta.env.VITE_BASE_URL || ''

  useEffect(() => {
    if (!token) return

    fetch(`${BASE_URL}/auth/revert-email/?token=${encodeURIComponent(token)}`)
      .then(async (res) => {
        const data = await res.json().catch(() => null)
        if (res.ok) {
          setStatus('success')
          setMessage(data?.message ?? 'Your email address has been reverted.')
        } else {
          setStatus('error')
          setMessage(data?.detail ?? 'Revert failed.')
        }
      })
      .catch(() => {
        setStatus('error')
        setMessage('Network error. Please try again.')
      })
  }, [token, BASE_URL])

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
            <Typography>Reverting your email…</Typography>
          </>
        )}

        {status === 'success' && (
          <>
            <Typography variant="h5" fontWeight={600}>Email reverted</Typography>
            <Typography sx={{ color: 'rgba(255,255,255,0.7)' }}>{message}</Typography>
            <Typography sx={{ color: 'rgba(255,255,255,0.7)' }}>
              We've also signed out every session on the account. Sign-in codes go to this address again.
            </Typography>
            <Button variant="contained" onClick={() => navigate('/login')}>Go to Login</Button>
          </>
        )}

        {status === 'error' && (
          <>
            <Typography variant="h5" fontWeight={600} color="error">Revert failed</Typography>
            <Typography sx={{ color: 'rgba(255,255,255,0.7)' }}>{message}</Typography>
            <Button variant="outlined" onClick={() => navigate('/login')}>Back to Login</Button>
          </>
        )}
      </Stack>
    </Box>
  )
}
