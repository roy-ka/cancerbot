import { useState, useEffect } from 'react'
import { Box, Button, Container, Typography, Checkbox, FormControlLabel, Alert, CircularProgress } from '@mui/material'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { isPendingDeletionResponse, loginPathForAuthFailure } from '../utils/authRedirect'

const BASE_URL = import.meta.env.VITE_BASE_URL || ''

export default function Terms() {
  const [accepted, setAccepted] = useState(false)
  const [termsText, setTermsText] = useState<string | null>(null)
  const [termsVersion, setTermsVersion] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const readonly = searchParams.get('readonly') === 'true'
  const isUpdate = searchParams.get('updated') === '1'

  useEffect(() => {
    fetch(`${BASE_URL}/terms/latest`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((data) => {
        setTermsText(data.text ?? '')
        setTermsVersion(data.version ?? null)
      })
      .catch((e) => {
        console.error('[Terms] failed to load:', e)
        setTermsText('Failed to load terms. Please refresh.')
      })
      .finally(() => setLoading(false))
  }, [])

  const handleAccept = async () => {
    if (readonly) {
      navigate(-1)
      return
    }
    setSubmitting(true)
    try {
      const res = await fetch(`${BASE_URL}/terms/accept`, {
        method: 'POST',
        credentials: 'include',
      })
      if (res.status === 401) {
        navigate(loginPathForAuthFailure(await isPendingDeletionResponse(res)), { replace: true })
        return
      }
      if (!res.ok) throw new Error('accept failed')
      navigate('/chat', { replace: true })
    } catch {
      navigate('/login', { replace: true })
    } finally {
      setSubmitting(false)
    }
  }

  const headline = isUpdate ? 'We updated our Terms and Conditions' : 'Terms and Conditions'

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h4" component="h1" gutterBottom>
          {headline}
        </Typography>
        {termsVersion && (
          <Typography variant="body2" color="textSecondary" gutterBottom>
            Version {termsVersion}
          </Typography>
        )}
      </Box>

      <Alert severity="warning" sx={{ mb: 3 }}>
        <strong>IMPORTANT:</strong> CancerBot is an advisory tool only and is NOT a substitute for professional medical advice.
        By using this app, you agree that you assume full responsibility for evaluating all information and will consult qualified healthcare professionals.
      </Alert>

      <Box sx={{ maxHeight: '400px', overflow: 'auto', border: '1px solid', borderColor: 'divider', p: 2, mb: 3, backgroundColor: 'background.paper' }}>
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={24} />
          </Box>
        ) : (
          <Typography component="pre" sx={{ fontFamily: 'inherit', whiteSpace: 'pre-wrap', fontSize: '0.875rem' }}>
            {termsText}
          </Typography>
        )}
      </Box>

      {!readonly && (
        <>
          <Box sx={{ mb: 3 }}>
            <FormControlLabel
              control={<Checkbox checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />}
              label="I have read and understand the Terms and Conditions. I accept full responsibility for using this app and will consult qualified healthcare professionals for medical decisions."
            />
          </Box>

          <Box sx={{ display: 'flex', gap: 2 }}>
            <Button
              variant="contained"
              color="primary"
              onClick={handleAccept}
              disabled={!accepted || submitting || loading}
            >
              {submitting ? 'Saving…' : 'Accept and Continue'}
            </Button>
            <Button variant="outlined" color="secondary" onClick={() => navigate('/login')}>
              Decline
            </Button>
          </Box>
        </>
      )}

      {readonly && (
        <Button variant="outlined" onClick={() => navigate(-1)}>
          Back
        </Button>
      )}
    </Container>
  )
}
