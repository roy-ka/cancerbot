import { IconButton, Box } from '@mui/material'
import { Brightness4, Brightness7 } from '@mui/icons-material'
import { useDarkMode } from '../context/ThemeContext'

export default function DarkModeToggle() {
  const { isDarkMode, toggleDarkMode } = useDarkMode()

  return (
    <Box
      sx={{
        position: 'fixed',
        top: 16,
        right: 16,
        zIndex: 1000,
      }}
    >
      <IconButton
        onClick={toggleDarkMode}
        sx={{
          backgroundColor: 'rgba(255,255,255,0.1)',
          '&:hover': {
            backgroundColor: 'rgba(255,255,255,0.2)',
          },
        }}
        title={isDarkMode ? 'Switch to light mode' : 'Switch to dark mode'}
      >
        {isDarkMode ? <Brightness7 /> : <Brightness4 />}
      </IconButton>
    </Box>
  )
}
