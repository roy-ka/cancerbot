import { useRef } from 'react'
import LoginDetails from '../components/LoginDetails'
import AuthPanel from '../components/AuthPanel'
import { Box, Grid, Typography } from '@mui/material'
import { cancerbotDark } from '../assets'

export default function Login() {
  const bgRef = useRef<HTMLDivElement | null>(null)
  const onMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const el = bgRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const x = (e.clientX - r.left) / r.width - 0.5
    const y = (e.clientY - r.top) / r.height - 0.5
    const mx = Math.max(-1, Math.min(1, x)) * 18
    const my = Math.max(-1, Math.min(1, y)) * 18
    el.style.setProperty('--mx', `${mx}px`)
    el.style.setProperty('--my', `${my}px`)
  }
  const onMouseLeave = () => {
    const el = bgRef.current
    if (!el) return
    el.style.setProperty('--mx', '0px')
    el.style.setProperty('--my', '0px')
  }
  return (
    <Box
      ref={bgRef}
      onMouseMove={onMouseMove}
      onMouseLeave={onMouseLeave}
      className="login-background"
    >
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: '100%', maxWidth: 1280 }}>
        <Box sx={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 2, mb: 4 }}>
          <img src={cancerbotDark} alt="cancerbot" style={{ width: 112, height: 112, borderRadius: 22 }} />
          <Typography
            sx={{
              fontSize: 112,
              lineHeight: '112px',
              fontWeight: 900,
              color: '#ffffff',
              letterSpacing: '0.04em',
              fontFamily: '"Nunito", sans-serif',
            }}
          >
            CANCER-BOT
          </Typography>
        </Box>

        <Grid container spacing={3} className="login-grid">
          <Grid size={{ xs: 0, md: 6 }} className="login-grid-item" sx={{ display: { xs: 'none', md: 'block' } }}>
            <Box className="login-details-container">
              <LoginDetails />
            </Box>
          </Grid>

          <Grid size={{ xs: 12, md: 6 }} className="login-grid-item login-auth-panel">
            <AuthPanel />
          </Grid>
        </Grid>
      </Box>
    </Box>
  )
}
