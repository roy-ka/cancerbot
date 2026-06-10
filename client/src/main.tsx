import React from 'react'
import ReactDOM from 'react-dom/client'
import * as Sentry from '@sentry/react'
import App from './App'
import { ThemeProvider as MuiThemeProvider } from '@mui/material/styles'
import CssBaseline from '@mui/material/CssBaseline'
import { ThemeProvider } from './context/ThemeContext'
import { darkTheme, lightTheme } from './theme'
import DarkModeToggle from './components/DarkModeToggle'
import { useDarkMode } from './context/ThemeContext'

const sentryDsn = import.meta.env.VITE_SENTRY_DSN
if (sentryDsn) {
  Sentry.init({
    dsn: sentryDsn,
    environment: import.meta.env.MODE,
    integrations: [Sentry.browserTracingIntegration()],
    tracesSampleRate: 0.1,
    sendDefaultPii: true,
  })
}

function Root() {
  const { isDarkMode } = useDarkMode()
  const currentTheme = isDarkMode ? darkTheme : lightTheme

  return (
    <MuiThemeProvider theme={currentTheme}>
      <CssBaseline />
      <DarkModeToggle />
      <App />
    </MuiThemeProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <Root />
    </ThemeProvider>
  </React.StrictMode>,
)
