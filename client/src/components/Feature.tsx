import { Box, Stack, Typography } from '@mui/material'

function Feature({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <Stack direction="row" spacing={1.5} alignItems="center">
      <Box
        sx={{
          color: 'primary.main',
          display: 'flex',
          alignItems: 'center',
        }}
      >
        {icon}
      </Box>
      <Typography variant="body1" fontWeight={600}>
        {text}
      </Typography>
    </Stack>
  )
}

export default Feature
