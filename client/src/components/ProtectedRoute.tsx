import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Box } from '@mui/material'

interface ProtectedRouteProps {
  children: React.ReactNode
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null)
  const [termsAccepted, setTermsAccepted] = useState<boolean | null>(null)

  useEffect(() => {
    // Check auth
    const baseUrl = import.meta.env.VITE_BASE_URL || ''
    fetch(`${baseUrl}/auth/check/`, {
      method: 'GET',
      credentials: 'include',
    })
      .then((res) => {
        setIsAuthenticated(res.ok)
      })
      .catch(() => {
        setIsAuthenticated(false)
      })

    // Check terms acceptance
    const accepted = localStorage.getItem('termsAccepted') === 'true'
    setTermsAccepted(accepted)
  }, [])

  if (isAuthenticated === null || termsAccepted === null) {
    return <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>Loading...</Box>
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  if (!termsAccepted) {
    return <Navigate to="/terms" replace />
  }

  return <>{children}</>
}
