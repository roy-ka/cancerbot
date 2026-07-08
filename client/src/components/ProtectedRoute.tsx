import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Box } from '@mui/material'

interface ProtectedRouteProps {
  children: React.ReactNode
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null)
  const [termsRedirect, setTermsRedirect] = useState<string | null>(null)

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const baseUrl = import.meta.env.VITE_BASE_URL || ''
        const controller = new AbortController()
        const timeout = setTimeout(() => controller.abort(), 5000)

        const res = await fetch(`${baseUrl}/auth/check/`, {
          method: 'GET',
          credentials: 'include',
          signal: controller.signal,
        })
        clearTimeout(timeout)

        if (!res.ok) {
          setIsAuthenticated(false)
          return
        }

        const data = await res.json()
        setIsAuthenticated(true)

        if (data.needs_terms_update) {
          const isUpdate = data.terms_version != null
          setTermsRedirect(isUpdate ? '/terms?updated=1' : '/terms')
        }
      } catch (e) {
        console.error('Auth check failed:', e)
        setIsAuthenticated(false)
      }
    }

    checkAuth()
  }, [])

  if (isAuthenticated === null) {
    return <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>Loading...</Box>
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  if (termsRedirect) {
    return <Navigate to={termsRedirect} replace />
  }

  return <>{children}</>
}
