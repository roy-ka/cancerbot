import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { ThemeProvider as MuiThemeProvider } from '@mui/material/styles'
import CssBaseline from '@mui/material/CssBaseline'
import { ThemeProvider } from './context/ThemeContext'
import { darkTheme } from './theme'
import { SchemaProvider } from './schema-monitor'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <MuiThemeProvider theme={darkTheme}>
        <CssBaseline />
        <SchemaProvider>
          <App />
        </SchemaProvider>
      </MuiThemeProvider>
    </ThemeProvider>
  </React.StrictMode>,
)
