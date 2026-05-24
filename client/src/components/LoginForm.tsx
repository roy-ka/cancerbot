import {
  Stack,
  TextField,
  FormControl,
  Button,
  FormControlLabel,
  Checkbox,
} from '@mui/material'
import React, { useState } from 'react'
import { useNavigate } from 'react-router'
import type { LoginPayload } from '../types'

export default function LoginForm({
  onForgotPassword,
}: {
  onForgotPassword?: () => void
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [rememberMe, setRememberMe] = useState(false)
  const navigate = useNavigate()

  const login = async (payload: LoginPayload) => {
    const BASE_URL = import.meta.env.VITE_BASE_URL

    const res = await fetch(`${BASE_URL}/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      credentials: 'include',
    })
    if (res.ok) {
      console.log('Login successful, redirecting to dashboard...')
      navigate('/chat')
    } else {
      res.json().then((err) => {
        throw new Error(err?.message ?? 'Login failed')
      })
    }
  }

  const onSubmit = (e: React.SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    login({ email, password, rememberMe })
      .then((res) => {
        console.log('Login successful:', res)
      })
      .catch((err) => {
        console.error('Login error:', err)
      })
  }
  const changeEmail = (e: React.ChangeEvent<HTMLInputElement>) => {
    const email = e.target.value
    setEmail(email)
  }

  const changePassword = (e: React.ChangeEvent<HTMLInputElement>) => {
    const password = e.target.value
    setPassword(password)
  }

  return (
    <FormControl component="form" onSubmit={onSubmit} sx={{ width: '100%' }}>
      <Stack spacing={2} sx={{ width: '100%' }}>
        <TextField
          fullWidth
          required
          id="email"
          name="email"
          label="Email"
          type="email"
          autoComplete="email"
          variant="outlined"
          onChange={changeEmail}
        />

        <TextField
          fullWidth
          required
          id="password"
          name="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          variant="outlined"
          onChange={changePassword}
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={rememberMe}
              onChange={(e) => setRememberMe(e.target.checked)}
            />
          }
          label="Remember me"
        />
        <Button type="submit" variant="contained" fullWidth>
          Submit
        </Button>
        {onForgotPassword && (
          <Button size="small" onClick={onForgotPassword}>
            Forgot password?
          </Button>
        )}
      </Stack>
    </FormControl>
  )
}
