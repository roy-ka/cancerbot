import { Box } from '@mui/material'

export default function messageList({
  messages,
  input,
}: {
  messages: React.ReactNode
  input: React.ReactNode
}) {
  return (
    <Box
      sx={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
      }}
    >
      {/* Messages */}
      <Box
        sx={{
          flex: 1,
          overflowY: 'auto',
          px: { xs: 2, md: 4 },
          py: 3,
        }}
      >
        {messages}
      </Box>

      {/* Input */}
      <Box
        sx={{
          borderTop: '1px solid rgba(255,255,255,0.08)',
          backdropFilter: 'blur(12px)',
          backgroundColor: 'rgba(20,25,40,0.85)',
          px: { xs: 2, md: 4 },
          py: 2,
        }}
      >
        {input}
      </Box>
    </Box>
  )
}
