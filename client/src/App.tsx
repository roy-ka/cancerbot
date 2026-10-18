import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Login from './pages/Login'
import Chat from './pages/Chat'
import Terms from './pages/Terms'
import Privacy from './pages/Privacy'
import Onboarding from './pages/Onboarding'
import ConfirmDeleteAccount from './pages/ConfirmDeleteAccount'
import ChangeEmail from './pages/ChangeEmail'
import ConfirmEmailChange from './pages/ConfirmEmailChange'
import RevertEmail from './pages/RevertEmail'
import SharedConversation from './pages/SharedConversation'
import Ninja from './pages/Ninja'
import ProtectedRoute from './components/ProtectedRoute'
import PublicRoute from './components/PublicRoute'
import VersionBadge from './components/VersionBadge'
import './App.css'

function App() {
  return (
    <BrowserRouter>
      <VersionBadge />
      <Routes>
        {/* Default */}
        <Route path="/" element={<Navigate to="/login" replace />} />

        {/* Public — redirect to /chat if already authenticated */}
        <Route path="/login" element={<PublicRoute><Login /></PublicRoute>} />
        <Route path="/terms" element={<Terms />} />
        <Route path="/privacy" element={<Privacy />} />
        <Route
          path="/onboarding"
          element={
            // key forces a full remount when navigating to/from /chat (also
            // wrapped in ProtectedRoute) — same component type at the same
            // tree position otherwise gets reused across the route change,
            // carrying over stale auth-check state from whichever page was
            // mounted first instead of re-checking for the new one.
            <ProtectedRoute key="onboarding">
              <Onboarding />
            </ProtectedRoute>
          }
        />
        <Route path="/confirm-delete" element={<ConfirmDeleteAccount />} />
        <Route path="/change-email" element={<ChangeEmail />} />
        <Route path="/confirm-email-change" element={<ConfirmEmailChange />} />
        <Route path="/revert-email" element={<RevertEmail />} />
        <Route path="/s/:token" element={<SharedConversation />} />

        {/* Protected App */}
        <Route
          path="/chat"
          element={
            <ProtectedRoute key="chat">
              <Chat />
            </ProtectedRoute>
          }
        />

        {/* Ninja-only admin view — not a ProtectedRoute: the ninja account
            has no users row for ProtectedRoute's DB-backed /auth/check/ to
            find, so Ninja.tsx does its own auth gate against /ninja/check/. */}
        <Route path="/ninja" element={<Ninja />} />

        {/* Catch-all - go to login, let ProtectedRoute handle redirects */}
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
