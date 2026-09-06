import { useEffect, useState } from 'react'
import {
  Box,
  Button,
  Container,
  Typography,
  TextField,
  MenuItem,
  Alert,
  CircularProgress,
} from '@mui/material'
import { useNavigate } from 'react-router-dom'
import { isPendingDeletionResponse, loginPathForAuthFailure } from '../utils/authRedirect'

const BASE_URL = import.meta.env.VITE_BASE_URL || ''

const AGE_BANDS = [
  { value: 'under_18', label: 'Under 18' },
  { value: '18_39', label: '18–39' },
  { value: '40_64', label: '40–64' },
  { value: '65_plus', label: '65+' },
]

const TREATMENT_STATUSES = [
  { value: 'newly_diagnosed', label: 'Newly diagnosed' },
  { value: 'in_active_treatment', label: 'In active treatment' },
  { value: 'post_treatment_surveillance', label: 'Post-treatment surveillance' },
  { value: 'recurrence_or_progression', label: 'Recurrence or progression' },
  { value: 'chronic', label: 'Managed as a chronic condition' },
]

type ProfileState = {
  cancer_type: string
  stage: string
  biomarkers: string
  age_band: string
  treatment_status: string
}

const EMPTY_PROFILE: ProfileState = {
  cancer_type: '',
  stage: '',
  biomarkers: '',
  age_band: '',
  treatment_status: '',
}

export default function Onboarding() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [existed, setExisted] = useState(false)
  const [profile, setProfile] = useState<ProfileState>(EMPTY_PROFILE)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${BASE_URL}/profile/me`, { credentials: 'include' })
      .then(async (res) => {
        if (!res.ok) {
          navigate(loginPathForAuthFailure(await isPendingDeletionResponse(res)), { replace: true })
          return null
        }
        return res.json()
      })
      .then((data) => {
        if (!data) return
        if (data.exists) {
          setExisted(true)
          setProfile({
            cancer_type: data.cancer_type ?? '',
            stage: data.stage ?? '',
            biomarkers: data.biomarkers ?? '',
            age_band: data.age_band ?? '',
            treatment_status: data.treatment_status ?? '',
          })
        }
      })
      .catch(() => navigate('/login', { replace: true }))
      .finally(() => setLoading(false))
  }, [navigate])

  const setField = (field: keyof ProfileState) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setProfile((prev) => ({ ...prev, [field]: e.target.value }))
  }

  const save = async (payload: Partial<ProfileState>) => {
    setSaving(true)
    setError(null)
    try {
      const res = await fetch(`${BASE_URL}/profile/me`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (res.status === 401) {
        navigate(loginPathForAuthFailure(await isPendingDeletionResponse(res)), { replace: true })
        return
      }
      if (!res.ok) throw new Error('Failed to save')
      navigate('/chat', { replace: true })
    } catch {
      setError('Something went wrong saving your profile. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const handleSave = () => save(profile)
  const handleSkip = () => save({})

  const handleClear = async () => {
    setSaving(true)
    setError(null)
    try {
      const res = await fetch(`${BASE_URL}/profile/me`, { method: 'DELETE', credentials: 'include' })
      if (res.status === 401) {
        navigate(loginPathForAuthFailure(await isPendingDeletionResponse(res)), { replace: true })
        return
      }
      if (!res.ok) throw new Error('Failed to clear')
      setProfile(EMPTY_PROFILE)
      setExisted(false)
    } catch {
      setError('Something went wrong clearing your profile. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <Container maxWidth="md" sx={{ py: 4, display: 'flex', justifyContent: 'center' }}>
        <CircularProgress size={24} />
      </Container>
    )
  }

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h4" component="h1" gutterBottom>
          Tell us a bit about your situation
        </Typography>
        <Typography variant="body2" color="textSecondary">
          Completely optional — this helps CancerBot frame answers more relevantly (for example, age-appropriate
          information, or noticing when something is more relevant to someone newly diagnosed versus in
          surveillance). You can skip this, edit it later from the account menu, or clear it out entirely at any
          time.
        </Typography>
      </Box>

      <Alert severity="info" sx={{ mb: 3 }}>
        This information helps tailor general answers — it does not turn CancerBot into a source of individualized
        treatment recommendations, and it's not a substitute for your own care team.
      </Alert>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mb: 3 }}>
        <TextField
          label="Cancer type / primary site"
          placeholder="e.g. Glioblastoma"
          value={profile.cancer_type}
          onChange={setField('cancer_type')}
          fullWidth
        />
        <TextField
          label="Stage"
          placeholder="e.g. IV"
          value={profile.stage}
          onChange={setField('stage')}
          fullWidth
        />
        <TextField
          label="Biomarkers / mutations"
          placeholder="e.g. IDH-wildtype, MGMT-unmethylated"
          value={profile.biomarkers}
          onChange={setField('biomarkers')}
          fullWidth
          multiline
          minRows={2}
        />
        <TextField
          select
          label="Age band"
          value={profile.age_band}
          onChange={setField('age_band')}
          fullWidth
        >
          <MenuItem value="">Prefer not to say</MenuItem>
          {AGE_BANDS.map((o) => (
            <MenuItem key={o.value} value={o.value}>
              {o.label}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          label="Treatment status"
          value={profile.treatment_status}
          onChange={setField('treatment_status')}
          fullWidth
        >
          <MenuItem value="">Prefer not to say</MenuItem>
          {TREATMENT_STATUSES.map((o) => (
            <MenuItem key={o.value} value={o.value}>
              {o.label}
            </MenuItem>
          ))}
        </TextField>
      </Box>

      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
        <Button variant="contained" color="primary" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
        {!existed && (
          <Button variant="outlined" onClick={handleSkip} disabled={saving}>
            Skip for now
          </Button>
        )}
        {existed && (
          <>
            <Button variant="outlined" color="secondary" onClick={handleClear} disabled={saving}>
              Clear profile
            </Button>
            <Button variant="text" onClick={() => navigate('/chat')} disabled={saving}>
              Back to chat
            </Button>
          </>
        )}
      </Box>
    </Container>
  )
}
