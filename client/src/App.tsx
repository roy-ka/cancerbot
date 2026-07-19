import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Login from './pages/Login'
import Chat from './pages/Chat'
import Terms from './pages/Terms'
import VerifyEmail from './pages/VerifyEmail'
import ResetPassword from './pages/ResetPassword'
import ConfirmDeleteAccount from './pages/ConfirmDeleteAccount'
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
        <Route path="/verify-email" element={<VerifyEmail />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/confirm-delete" element={<ConfirmDeleteAccount />} />

        {/* Protected App */}
        <Route
          path="/chat"
          element={
            <ProtectedRoute>
              <Chat />
            </ProtectedRoute>
          }
        />

        {/* Catch-all - go to login, let ProtectedRoute handle redirects */}
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
