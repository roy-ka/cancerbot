import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { Box, CircularProgress, Typography, Button, Stack } from '@mui/material'

export default function ConfirmEmailChange() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token')
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>(
    token ? 'loading' : 'error',
  )
  const [message, setMessage] = useState(
    token ? '' : 'No confirmation token found in the link.',
  )
  const BASE_URL = import.meta.env.VITE_BASE_URL || ''

  useEffect(() => {
    if (!token) return

    fetch(`${BASE_URL}/auth/confirm-email-change/?token=${encodeURIComponent(token)}`)
      .then(async (res) => {
        const data = await res.json().catch(() => null)
        if (res.ok) {
          setStatus('success')
          setMessage(data?.message ?? 'Email updated. Please log in with your new email.')
        } else {
          setStatus('error')
          setMessage(data?.detail ?? 'Confirmation failed.')
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
            <Typography>Confirming your new email…</Typography>
          </>
        )}

        {status === 'success' && (
          <>
            <Typography variant="h5" fontWeight={600}>Email updated!</Typography>
            <Typography sx={{ color: 'rgba(255,255,255,0.7)' }}>{message}</Typography>
            <Button variant="contained" onClick={() => navigate('/login')}>Go to Login</Button>
          </>
        )}

        {status === 'error' && (
          <>
            <Typography variant="h5" fontWeight={600} color="error">Confirmation failed</Typography>
            <Typography sx={{ color: 'rgba(255,255,255,0.7)' }}>{message}</Typography>
            <Button variant="outlined" onClick={() => navigate('/login')}>Back to Login</Button>
          </>
        )}
      </Stack>
    </Box>
  )
}
