import { createContext, useContext } from 'react'

interface ThemeContextType {
  isDarkMode: boolean
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined)

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // Dark mode is always on
  document.documentElement.setAttribute('data-theme', 'dark')

  return (
    <ThemeContext.Provider value={{ isDarkMode: true }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useDarkMode() {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error('useDarkMode must be used within ThemeProvider')
  }
  return context
}
