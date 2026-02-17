import { useState, useEffect } from 'react'
import { Box, Button, Typography } from '@mui/material'
import LoginForm from './LoginForm'
import RegistrationForm from './RegistrationForm'
import { useNavigate } from 'react-router'
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

export default function AuthPanel() {
  const [isLogin, setIsLogin] = useState(true)
  const changeToLogin = () => setIsLogin(true)
  const navigate = useNavigate()
  const BASE_URL = import.meta.env.VITE_BASE_URL

  useEffect(() => {
    fetch(`${BASE_URL}/auth/check`, {
      method: 'GET',
      credentials: 'include',
    })
      .then((res) => {
        if (res.ok) {
          console.log('Already logged in, redirecting to dashboard...')
          navigate('/chat', { replace: true })
        }
      })
      .catch(() => {
        console.log('Not logged in, staying on auth panel')
        // Not logged in, stay on auth panel
      })
  }, [navigate, BASE_URL])

  return (
    <Box className="auth-panel">
      <Box className="auth-panel-header">
        <Typography variant="h5" fontWeight={900} className="auth-panel-title">
          {isLogin ? 'Welcome back' : 'Create your account'}
        </Typography>
        <Typography variant="body2" className="auth-panel-subtitle">
          {isLogin
            ? 'Log in to continue to cancerbot.'
            : 'Register to start saving sources and building claims.'}
        </Typography>
      </Box>

      <AuthButtons isLogin={isLogin} setIsLogin={setIsLogin} />

      <Box className="auth-form-container">
        {isLogin ? (
          <LoginForm />
        ) : (
          <RegistrationForm changeToLogin={changeToLogin} />
        )}
      </Box>
    </Box>
  )
}
