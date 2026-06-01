import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Box } from '@mui/material'

interface ProtectedRouteProps {
  children: React.ReactNode
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null)
  const BASE_URL = import.meta.env.VITE_BASE_URL

  useEffect(() => {
    fetch(`${BASE_URL}/auth/check/`, {
      method: 'GET',
      credentials: 'include',
    })
      .then((res) => {
        setIsAuthenticated(res.ok)
      })
      .catch(() => {
        setIsAuthenticated(false)
      })
  }, [BASE_URL])

  if (isAuthenticated === null) {
    return <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>Loading...</Box>
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}
