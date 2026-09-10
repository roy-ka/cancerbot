import { createTheme } from '@mui/material/styles'

// Design rule: every popup, menu, and dialog gets a fully OPAQUE surface —
// no rgba(...) alpha, no relying on backdropFilter blur to hide what's
// bleeding through underneath. A translucent dialog/menu paper (rgba alpha
// < 1) lets the page content behind it show through and become unreadable
// once it's anything more than a couple of short lines — this bit a Dialog
// added without realizing the app-wide default (`background.paper`) is a 6%
// opacity overlay, not a solid color. Set once here so every MuiDialog/
// MuiMenu/MuiPopover paper is solid by default; don't override with an rgba
// background on an individual component.
const DIALOG_SURFACE_DARK = {
  backgroundColor: 'rgb(18,25,45)',
  backgroundImage: 'none',
  border: '1px solid rgba(255,255,255,0.1)',
  boxShadow: '0 20px 60px rgba(0,0,0,0.4)',
}
const DIALOG_SURFACE_LIGHT = {
  backgroundColor: 'rgb(255,255,255)',
  backgroundImage: 'none',
  border: '1px solid rgba(0,0,0,0.12)',
  boxShadow: '0 20px 60px rgba(0,0,0,0.15)',
}

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
    MuiDialog: {
      styleOverrides: {
        paper: DIALOG_SURFACE_DARK,
      },
    },
    MuiMenu: {
      styleOverrides: {
        paper: DIALOG_SURFACE_DARK,
      },
    },
    MuiPopover: {
      styleOverrides: {
        paper: DIALOG_SURFACE_DARK,
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
    MuiDialog: {
      styleOverrides: {
        paper: DIALOG_SURFACE_LIGHT,
      },
    },
    MuiMenu: {
      styleOverrides: {
        paper: DIALOG_SURFACE_LIGHT,
      },
    },
    MuiPopover: {
      styleOverrides: {
        paper: DIALOG_SURFACE_LIGHT,
      },
    },
  },
})

export const theme = darkTheme
