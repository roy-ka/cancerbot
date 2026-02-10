import { Box, Typography } from '@mui/material'

export default function ConversationList() {
  return (
    <Box
      sx={{
        flex: 1,
        overflowY: 'auto',
        px: 2,
        py: 2,
      }}
    >
      <Typography
        sx={{
          fontWeight: 800,
          fontSize: 14,
          color: 'rgba(255,255,255,0.75)',
          mb: 2,
        }}
      >
        Conversations
      </Typography>

      {/* Conversation item */}
      <Box
        sx={{
          p: 1.5,
          borderRadius: 2,
          mb: 1,
          cursor: 'pointer',
          background:
            'linear-gradient(135deg, rgba(124,92,255,0.18), rgba(47,227,198,0.08))',
          border: '1px solid rgba(255,255,255,0.08)',
          '&:hover': {
            background:
              'linear-gradient(135deg, rgba(124,92,255,0.28), rgba(47,227,198,0.12))',
          },
        }}
      >
        <Typography fontWeight={700} fontSize={14}>
          Ketogenic diet & IGF-1
        </Typography>
        <Typography fontSize={12} sx={{ color: 'rgba(255,255,255,0.6)' }}>
          Last message · 2h ago
        </Typography>
      </Box>
    </Box>
  )
}
