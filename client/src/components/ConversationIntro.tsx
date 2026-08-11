import { useMemo } from 'react'
import { Box, Chip, Stack, Tooltip, Typography } from '@mui/material'
import { RAG_EXPLAINER, pickTips } from '../utils/introContent'

/**
 * Intro shown in place of an empty conversation, styled as an assistant
 * message so it reads as CancerBot's opening turn.
 *
 * It is purely client-side: it is never sent to the backend or persisted, and
 * it disappears as soon as the conversation has any message (the optimistic
 * user message alone is enough), so it never becomes part of the thread.
 */
export default function ConversationIntro({
  onExampleClick,
}: {
  onExampleClick?: (text: string) => void
}) {
  // Pick once per mount — a fresh conversation remounts this and re-rolls.
  const tips = useMemo(() => pickTips(), [])

  return (
    <Box
      sx={{
        mb: 2,
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'flex-start',
      }}
    >
      <Box
        className="message-bubble-assistant"
        data-testid="conversation-intro"
        sx={{
          maxWidth: { xs: '90%', sm: '70%' },
          px: 3,
          py: 2,
          position: 'relative',
          backgroundColor: 'rgba(255,255,255,0.15)',
        }}
      >
        <Typography variant="body1" sx={{ lineHeight: 1.7 }}>
          This is a{' '}
          <Tooltip
            title={
              <Box sx={{ p: 1 }}>
                <Typography variant="body2" sx={{ lineHeight: 1.7 }}>
                  {RAG_EXPLAINER}
                </Typography>
              </Box>
            }
            arrow
            enterDelay={150}
            enterTouchDelay={0}
            leaveTouchDelay={6000}
            slotProps={{
              tooltip: {
                sx: {
                  opacity: 1,
                  bgcolor: 'rgba(17, 24, 39, 0.98)',
                  backdropFilter: 'none',
                  maxWidth: 420,
                },
              },
            }}
          >
            {/* tabIndex keeps the explanation reachable without a pointer —
                MUI's Tooltip opens on focus as well as hover. */}
            <Box
              component="span"
              data-testid="rag-link"
              tabIndex={0}
              sx={{
                color: 'primary.main',
                fontWeight: 700,
                borderBottom: '1px dashed',
                borderColor: 'primary.main',
                cursor: 'help',
              }}
            >
              RAG
            </Box>
          </Tooltip>{' '}
          implementation. To get the best answers, add context, keywords and
          such.
        </Typography>

        <Typography
          variant="caption"
          sx={{
            display: 'block',
            mt: 2.5,
            mb: 1,
            textTransform: 'uppercase',
            letterSpacing: 1,
            color: 'rgba(255,255,255,0.45)',
          }}
        >
          Try asking
        </Typography>

        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
          {tips.map((tip) => (
            <Chip
              key={tip}
              label={tip}
              data-testid="intro-tip"
              onClick={() => onExampleClick?.(tip)}
              variant="outlined"
              sx={{
                height: 'auto',
                maxWidth: '100%',
                py: 0.75,
                cursor: 'pointer',
                color: 'rgba(255,255,255,0.85)',
                borderColor: 'rgba(255,255,255,0.25)',
                '& .MuiChip-label': {
                  whiteSpace: 'normal',
                  display: 'block',
                  textAlign: 'left',
                },
                '&:hover': { borderColor: 'primary.main' },
              }}
            />
          ))}
        </Stack>
      </Box>
    </Box>
  )
}
