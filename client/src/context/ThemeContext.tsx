export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // Dark mode is always on
  document.documentElement.setAttribute('data-theme', 'dark')

  return <>{children}</>
}
