import { useEffect, useState } from 'react'
import { Box, Button, Typography } from '@mui/material'
import LoginForm from './LoginForm'
import RegistrationForm from './RegistrationForm'
import WaitlistForm from './WaitlistForm'
import ForgotPasswordForm from './ForgotPasswordForm'
import type { AuthButtonsProps } from '../types'

function AuthButtons({ isLogin, setIsLogin }: AuthButtonsProps) {
  return (
    <Box className="auth-buttons">
      <Button
        type="button"
        onClick={() => setIsLogin(true)}
        className={`auth-button ${isLogin ? 'active' : ''}`}
      >
        Login
      </Button>

      <Button
        type="button"
        onClick={() => setIsLogin(false)}
        className={`auth-button ${!isLogin ? 'active' : ''}`}
      >
        Register
      </Button>
    </Box>
  )
}

type View = 'login' | 'register' | 'forgot'

export default function AuthPanel() {
  const [view, setView] = useState<View>('login')
  const [registrationOpen, setRegistrationOpen] = useState(true)
  const BASE_URL = import.meta.env.VITE_BASE_URL || ''

  useEffect(() => {
    if (view !== 'register') return
    let cancelled = false
    fetch(`${BASE_URL}/auth/registration_status/`)
      .then((res) => res.json())
      .then((data) => {
        if (!cancelled) setRegistrationOpen(data.open !== false)
      })
      .catch(() => {
        // If the status check itself fails, fall back to showing the
        // registration form — the backend still enforces the cap server-side.
        if (!cancelled) setRegistrationOpen(true)
      })
    return () => {
      cancelled = true
    }
  }, [view, BASE_URL])

  const titles: Record<View, string> = {
    login: 'Welcome back',
    register: registrationOpen ? 'Create your account' : "We're full for now",
    forgot: 'Reset your password',
  }
  const subtitles: Record<View, string> = {
    login: 'Log in to continue to cancerbot.',
    register: registrationOpen
      ? 'Register to start saving sources and exploring evidence.'
      : "We're limiting new signups while we grow slowly.",
    forgot: "We'll send a reset link to your email.",
  }

  return (
    <Box className="auth-panel">
      <Box className="auth-panel-header">
        <Typography variant="h5" fontWeight={900} className="auth-panel-title">
          {titles[view]}
        </Typography>
        <Typography variant="body2" className="auth-panel-subtitle">
          {subtitles[view]}
        </Typography>
      </Box>

      {view !== 'forgot' && (
        <AuthButtons
          isLogin={view === 'login'}
          setIsLogin={(v) => setView(v ? 'login' : 'register')}
        />
      )}

      <Box className="auth-form-container">
        {view === 'login' && (
          <LoginForm onForgotPassword={() => setView('forgot')} />
        )}
        {view === 'register' && (
          registrationOpen ? (
            <RegistrationForm changeToLogin={() => setView('login')} />
          ) : (
            <WaitlistForm changeToLogin={() => setView('login')} />
          )
        )}
        {view === 'forgot' && (
          <ForgotPasswordForm onBack={() => setView('login')} />
        )}
      </Box>
    </Box>
  )
}
