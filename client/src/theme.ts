import { createTheme } from '@mui/material/styles'

const commonConfig = {
  shape: { borderRadius: 18 },
  typography: {
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial',
    h5: { fontWeight: 700 },
    h6: { fontWeight: 700 },
    button: { textTransform: 'none', fontWeight: 700 },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: { margin: 0 },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: { borderRadius: 14, paddingInline: 16, paddingBlock: 10 },
      },
    },
    MuiTextField: {
      defaultProps: {
        variant: 'outlined' as const,
      },
    },
  },
}

export const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: '#7C5CFF' },
    secondary: { main: '#2FE3C6' },
    background: {
      default: '#0B1220',
      paper: 'rgba(255,255,255,0.06)',
    },
    text: {
      primary: 'rgba(255,255,255,0.92)',
      secondary: 'rgba(255,255,255,0.66)',
    },
    divider: 'rgba(255,255,255,0.10)',
  },
  ...commonConfig,
  components: {
    ...commonConfig.components,
    MuiCard: {
      styleOverrides: {
        root: {
          border: '1px solid rgba(255,255,255,0.10)',
          backdropFilter: 'blur(10px)',
          backgroundImage: 'none',
        },
      },
    },
  },
})

export const lightTheme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#7C5CFF' },
    secondary: { main: '#2FE3C6' },
    background: {
      default: '#FFFFFF',
      paper: 'rgba(0,0,0,0.02)',
    },
    text: {
      primary: 'rgba(0,0,0,0.87)',
      secondary: 'rgba(0,0,0,0.60)',
    },
    divider: 'rgba(0,0,0,0.12)',
  },
  ...commonConfig,
  components: {
    ...commonConfig.components,
    MuiCard: {
      styleOverrides: {
        root: {
          border: '1px solid rgba(0,0,0,0.12)',
          backdropFilter: 'blur(10px)',
        },
      },
    },
  },
})

export const theme = darkTheme
