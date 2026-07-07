import {
  Box,
  Typography,
  Stack,
  useMediaQuery,
  useTheme,
  Card,
  Grid,
} from '@mui/material'
import SearchOutlinedIcon from '@mui/icons-material/SearchOutlined'
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined'
import PsychologyOutlinedIcon from '@mui/icons-material/PsychologyOutlined'
import Feature from './Feature'
import { chatBackground as chatBg } from '../assets'

export default function LoginDetails() {
  const theme = useTheme()
  const isMdUp = useMediaQuery(theme.breakpoints.up('md'))

  return (
    <Card className="login-details-card">
      {/* Top branding */}
      <Stack spacing={2} width="100%">
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
                <Typography variant={isMdUp ? 'h5' : 'h6'} fontWeight={800}>
                  Your personal knowledge lab
                </Typography>

                <Stack spacing={1.2} sx={{ mt: 0.5 }}>
                  <Feature
                    icon={<SearchOutlinedIcon />}
                    text="Search across medical sources"
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

          </Grid>
        </Box>
      </Stack>
    </Card>
  )
}
