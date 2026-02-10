import { Box, Grid } from '@mui/material'

export default function ChatLayout({
  conversations,
  children,
}: {
  conversations: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <Box
      sx={{
        minHeight: '100dvh',
        width: '100%',
        display: 'flex',
        backgroundColor: 'background.default',
      }}
    >
      <Grid container sx={{ flex: 1 }}>
        {/* LEFT: Conversations */}
        <Grid
          size={12}
          // md={3}
          // lg={2.6}
          sx={{
            borderRight: '1px solid rgba(255,255,255,0.08)',
            backdropFilter: 'blur(10px)',
            background:
              'linear-gradient(180deg, rgba(20,30,45,0.85), rgba(15,20,35,0.85))',
            display: 'flex',
            flexDirection: 'column',
            minHeight: '100dvh',
          }}
        >
          {conversations}
        </Grid>

        <Grid
          size={12}
          // md={9}
          // lg={9.4}
          sx={{
            display: 'flex',
            flexDirection: 'column',
            minHeight: '100dvh',
          }}
        >
          {children}
        </Grid>
      </Grid>
    </Box>
  )
}
