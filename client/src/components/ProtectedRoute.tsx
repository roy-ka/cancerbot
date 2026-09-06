import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Box } from '@mui/material'
import { isPendingDeletionResponse, loginPathForAuthFailure } from '../utils/authRedirect'

interface ProtectedRouteProps {
  children: React.ReactNode
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null)
  const [termsRedirect, setTermsRedirect] = useState<string | null>(null)
  const [needsOnboarding, setNeedsOnboarding] = useState(false)
  const [pendingDeletion, setPendingDeletion] = useState(false)

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
          // A session rejected specifically because deletion was scheduled
          // from another device otherwise bounces to /login with no
          // explanation — surface it via a query param the login page reads.
          if (await isPendingDeletionResponse(res)) {
            setPendingDeletion(true)
          }
          setIsAuthenticated(false)
          return
        }

        const data = await res.json()
        setIsAuthenticated(true)

        if (data.needs_terms_update) {
          const isUpdate = data.terms_version != null
          setTermsRedirect(isUpdate ? '/terms?updated=1' : '/terms')
        } else if (data.needs_onboarding) {
          setNeedsOnboarding(true)
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
    return <Navigate to={loginPathForAuthFailure(pendingDeletion)} replace />
  }

  if (termsRedirect) {
    return <Navigate to={termsRedirect} replace />
  }

  if (needsOnboarding) {
    return <Navigate to="/onboarding" replace />
  }

  return <>{children}</>
}
