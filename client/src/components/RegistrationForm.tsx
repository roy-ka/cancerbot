import React, { useState } from 'react'
import { Stack, TextField, FormControl, Button } from '@mui/material'

type RegistrationPayload = {
  email: string
  password: string
  name: string
}

export default function RegistrationForm({
  changeToLogin,
}: {
  changeToLogin: () => void
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [emailError, setEmailError] = useState(false)
  const [passwordError, setPasswordError] = useState(false)
  const [name, setName] = useState('')

  const verifyEmail = (email: string) => {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email === ''
  }

  const verifyPassword = (password: string) => {
    return password.length >= 6 || password === ''
  }

  const register = async (payload: RegistrationPayload) => {
    const res = await fetch('http://localhost:8000/auth/register', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => null)
      throw new Error(err?.message ?? 'Login failed')
    }
  }

  const onSubmit = (e: React.SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (emailError || passwordError) {
      return
    }
    register({ email, password, name })
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
    setEmailError(!verifyEmail(email))
  }

  const changePassword = (e: React.ChangeEvent<HTMLInputElement>) => {
    const password = e.target.value
    setPassword(password)
    setPasswordError(!verifyPassword(password))
  }
  const changeName = (e: React.ChangeEvent<HTMLInputElement>) => {
    const name = e.target.value
    setName(name)
  }

  return (
    <Stack spacing={2} sx={{ width: '100%' }}>
      <FormControl component="form" onSubmit={onSubmit} sx={{ width: '100%' }}>
        <Stack spacing={2} sx={{ width: '100%' }}>
          <TextField
            fullWidth
            required
            id="name"
            name="name"
            label="Full name"
            type="name"
            autoComplete="name"
            variant="outlined"
            onChange={changeName}
          />

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
            error={emailError}
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
            error={emailError}
          />
          <Button type="submit" variant="contained" fullWidth>
            Submit
          </Button>
        </Stack>
      </FormControl>
      <Button onClick={() => changeToLogin()}>
        Already have an account? Login
      </Button>
    </Stack>
  )
}
