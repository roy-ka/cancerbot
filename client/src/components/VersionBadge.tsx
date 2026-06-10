import { Box, Chip } from '@mui/material'

export default function VersionBadge() {
  const version = import.meta.env.VITE_VERSION
  const showBadge = import.meta.env.VITE_SHOW_DEV_BADGE === 'true'

  if (!showBadge || !version) return null

  return (
    <Box sx={{ position: 'fixed', top: 8, right: 8, zIndex: 1300 }}>
      <Chip
        label={`${version.toUpperCase()} - Under Development`}
        color="warning"
        variant="outlined"
        size="small"
        sx={{ fontWeight: 600 }}
      />
    </Box>
  )
}
