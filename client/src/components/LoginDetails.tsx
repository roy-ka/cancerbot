import {
  Box,
  Typography,
  Stack,
  Chip,
  useMediaQuery,
  useTheme,
  Card,
  Grid,
} from '@mui/material'
import SearchOutlinedIcon from '@mui/icons-material/SearchOutlined'
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined'
import PsychologyOutlinedIcon from '@mui/icons-material/PsychologyOutlined'
import Feature from './Feature'
import chatBg from '../assets/chat_background.png'

export default function LoginDetails() {
  const theme = useTheme()
  const isMdUp = useMediaQuery(theme.breakpoints.up('md'))

  return (
    <Card className="login-details-card">
      {/* Top branding */}
      <Stack spacing={2} width="100%">
        <Stack direction="row" spacing={1.5} alignItems="center" mb={2}>
          <Box className="login-details-logo">🦀</Box>

          <Box>
            <Typography variant="h6" fontWeight={700}>
              cancerbot
            </Typography>
          </Box>
        </Stack>

        <Stack spacing={1} mb={2} alignItems="flex-start">
          <Typography
            variant="body1"
            fontWeight={700}
            className="login-details-tagline"
            align="left"
          >
            Evidence-aware. Claim-curious.
            <br />
            Slightly caffeinated.
          </Typography>
        </Stack>

        {/* Feature card */}
        <Box
          className="login-details-feature-card"
          style={{ backgroundImage: `url(${chatBg})`, alignItems: 'stretch' }}
        >
          <Grid container spacing={2.5} alignItems="stretch">
            {/* Left content */}
            <Grid size={12}>
              <Stack spacing={1.6}>
                <Chip label="New" size="small" className="login-details-chip" />

                <Typography variant={isMdUp ? 'h5' : 'h6'} fontWeight={800}>
                  Your personal
                  <br />
                  knowledge lab
                </Typography>

                <Stack spacing={1.2} sx={{ mt: 0.5 }}>
                  <Feature
                    icon={<SearchOutlinedIcon />}
                    text="Search across sources + claims"
                  />
                  <Feature
                    icon={<DescriptionOutlinedIcon />}
                    text="Build structured evidence trails"
                  />
                  <Feature
                    icon={<PsychologyOutlinedIcon />}
                    text="RAG-friendly by design"
                  />
                </Stack>
              </Stack>
            </Grid>

            {/* Tip row */}
            <Grid size={12}>
              <Box className="login-details-tip">
                <Stack direction="row" spacing={1.5} alignItems="flex-start">
                  <Box className="login-details-tip-dot" />
                  <Typography
                    variant="body2"
                    sx={{ color: 'rgba(255,255,255,0.72)' }}
                  >
                    <strong style={{ color: 'rgba(255,255,255,0.88)' }}>
                      Tip:
                    </strong>{' '}
                    Use a long passphrase.
                    <br />
                    Your future self will send thanks.
                  </Typography>
                </Stack>
              </Box>
            </Grid>
          </Grid>
        </Box>
      </Stack>
    </Card>
  )
}
