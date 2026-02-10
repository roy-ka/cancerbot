import { useState } from 'react'
import { Box, Button, Typography } from '@mui/material'
import LoginForm from './LoginForm'
import RegistrationForm from './RegistrationForm'

type AuthButtonsProps = {
  isLogin: boolean
  setIsLogin: (val: boolean) => void
}

function AuthButtons({ isLogin, setIsLogin }: AuthButtonsProps) {
  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 0,
        p: 0.75,
        borderRadius: 999,
        backgroundColor: 'rgba(255,255,255,0.06)',
        border: '1px solid rgba(255,255,255,0.10)',
        backdropFilter: 'blur(10px)',
      }}
    >
      <Button
        type="button"
        onClick={() => setIsLogin(true)}
        sx={{
          borderRadius: 999,
          py: 1.1,
          fontWeight: 800,
          textTransform: 'none',
          color: isLogin ? 'rgba(255,255,255,0.92)' : 'rgba(255,255,255,0.65)',
          background: isLogin
            ? 'linear-gradient(135deg, rgba(124,92,255,0.70), rgba(47,227,198,0.28))'
            : 'transparent',
          border: isLogin
            ? '1px solid rgba(255,255,255,0.10)'
            : '1px solid transparent',
          boxShadow: isLogin ? '0 10px 22px rgba(0,0,0,0.25)' : 'none',
          '&:hover': {
            background: isLogin
              ? 'linear-gradient(135deg, rgba(124,92,255,0.75), rgba(47,227,198,0.32))'
              : 'rgba(255,255,255,0.06)',
          },
        }}
      >
        Login
      </Button>

      <Button
        type="button"
        onClick={() => setIsLogin(false)}
        sx={{
          borderRadius: 999,
          py: 1.1,
          fontWeight: 800,
          textTransform: 'none',
          color: !isLogin ? 'rgba(255,255,255,0.92)' : 'rgba(255,255,255,0.65)',
          background: !isLogin
            ? 'linear-gradient(135deg, rgba(124,92,255,0.70), rgba(47,227,198,0.28))'
            : 'transparent',
          border: !isLogin
            ? '1px solid rgba(255,255,255,0.10)'
            : '1px solid transparent',
          boxShadow: !isLogin ? '0 10px 22px rgba(0,0,0,0.25)' : 'none',
          '&:hover': {
            background: !isLogin
              ? 'linear-gradient(135deg, rgba(124,92,255,0.75), rgba(47,227,198,0.32))'
              : 'rgba(255,255,255,0.06)',
          },
        }}
      >
        Register
      </Button>
    </Box>
  )
}

export default function AuthPanel() {
  const [isLogin, setIsLogin] = useState(true)
  const changeToLogin = () => setIsLogin(true)

  return (
    <Box
      sx={{
        width: '100%',
        maxWidth: 460,
        height: '100%',
        mx: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: 2.5,
        border: '1px solid rgba(255,255,255,0.10)',
        borderRadius: 1,
        p: { xs: 3, sm: 4 },
        backgroundColor: 'rgba(255,255,255,0.06)',
        boxShadow: '0 18px 50px rgba(0,0,0,0.35)',
        backdropFilter: 'blur(12px)',
      }}
    >
      <Box>
        <Typography
          variant="h5"
          fontWeight={900}
          sx={{ color: 'rgba(255,255,255,0.92)' }}
        >
          {isLogin ? 'Welcome back' : 'Create your account'}
        </Typography>
        <Typography
          variant="body2"
          sx={{ color: 'rgba(255,255,255,0.66)', mt: 0.5 }}
        >
          {isLogin
            ? 'Log in to continue to cancerbot.'
            : 'Register to start saving sources and building claims.'}
        </Typography>
      </Box>

      <AuthButtons isLogin={isLogin} setIsLogin={setIsLogin} />

      <Box
        sx={{
          p: { xs: 3, sm: 3.5 },
          borderRadius: 1,
          backgroundColor: 'rgba(255,255,255,0.06)',
          border: '1px solid rgba(255,255,255,0.10)',
          boxShadow: '0 18px 50px rgba(0,0,0,0.35)',
          backdropFilter: 'blur(12px)',
          // Form look (labels + underline like the design)
          '& .MuiFormLabel-root': {
            color: 'rgba(255,255,255,0.70)',
            fontWeight: 650,
          },
          '& .MuiInputBase-root': {
            color: 'rgba(255,255,255,0.92)',
          },
          '& .MuiInput-underline:before': {
            borderBottomColor: 'rgba(255,255,255,0.16)',
          },
          '& .MuiInput-underline:hover:not(.Mui-disabled):before': {
            borderBottomColor: 'rgba(255,255,255,0.28)',
          },
          '& .MuiInput-underline:after': {
            borderBottomColor: 'rgba(124,92,255,0.70)',
          },
          '& .MuiFormHelperText-root': {
            color: 'rgba(255,255,255,0.60)',
          },
        }}
      >
        {isLogin ? (
          <LoginForm />
        ) : (
          <RegistrationForm changeToLogin={changeToLogin} />
        )}
      </Box>
    </Box>
  )
}
