import { createTheme } from '@mui/material/styles'

export const theme = createTheme({
  palette: {
    mode: 'dark', // switch to "light" if you want the whole app light
    primary: { main: '#7C5CFF' }, // purple
    secondary: { main: '#2FE3C6' }, // teal
    background: {
      default: '#0B1220', // page background
      paper: 'rgba(255,255,255,0.06)', // cards/panels (glass)
    },
    text: {
      primary: 'rgba(255,255,255,0.92)',
      secondary: 'rgba(255,255,255,0.66)',
    },
    divider: 'rgba(255,255,255,0.10)',
  },

  shape: { borderRadius: 18 },

  typography: {
    fontFamily:
      'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial',
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
    MuiCard: {
      styleOverrides: {
        root: {
          border: '1px solid rgba(255,255,255,0.10)',
          backdropFilter: 'blur(10px)',
          backgroundImage: 'none',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: { borderRadius: 14, paddingInline: 16, paddingBlock: 10 },
      },
    },
    MuiTextField: {
      defaultProps: {
        variant: 'outlined',
      },
    },
  },
})
