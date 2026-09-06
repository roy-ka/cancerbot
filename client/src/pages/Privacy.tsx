import { Box, Container, Typography, Alert, Button } from '@mui/material'
import { useNavigate } from 'react-router-dom'

export default function Privacy() {
  const navigate = useNavigate()

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h4" component="h1" gutterBottom>
          Privacy
        </Typography>
        <Typography variant="body2" color="textSecondary">
          What CancerBot actually does with what you type — described against how the app is built today, not aspirationally.
        </Typography>
      </Box>

      <Alert severity="info" sx={{ mb: 3 }}>
        This page explains data handling. It is not a substitute for the Terms and Conditions, and it isn't legal advice.
      </Alert>

      <Box sx={{ mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Your conversations are stored, not end-to-end encrypted
        </Typography>
        <Typography variant="body2" sx={{ mb: 1 }}>
          Every message you send and every answer you receive is saved in our database so your conversation history is there
          when you come back. This storage is not end-to-end encrypted — it is protected the way any application database is
          (access controls, infrastructure security), not with encryption that only you can unlock.
        </Typography>
        <Typography variant="body2">
          Deleting a conversation from the sidebar removes it from your view immediately, but the underlying record is kept
          (soft-deleted) until your account itself is deleted — see "Deleting your account" below.
        </Typography>
      </Box>

      <Box sx={{ mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          A privileged support account can read conversations
        </Typography>
        <Typography variant="body2">
          CancerBot has an internal admin ("ninja") account used for debugging and support. It can open any user's
          conversation and post a message into it to test or troubleshoot a response. Those support messages are flagged so
          they never show up in your own view of the conversation — but the admin account genuinely can read what you've
          written. We're stating this plainly because it's the kind of thing you'd want to know before sharing something
          sensitive.
        </Typography>
      </Box>

      <Box sx={{ mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          What gets sent to outside services
        </Typography>
        <Typography variant="body2" sx={{ mb: 1 }}>
          To generate an answer, your message text is sent to Groq (or Gemini, as an automatic fallback if Groq is
          unavailable). Key terms extracted from your message are also sent, as ordinary search queries, to PubMed,
          CrossRef, Wikipedia, and ClinicalTrials.gov to find supporting evidence.
        </Typography>
        <Typography variant="body2">
          <strong>No private or identifying account data</strong> — your name or email — is sent to any of these outside
          services. They only ever see whatever text you choose to put in a message.
        </Typography>
      </Box>

      <Box sx={{ mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Logging
        </Typography>
        <Typography variant="body2">
          When enabled, application logs (timing, errors, request metadata) are forwarded to our logging provider, Axiom.
          These logs do not include the text of your messages or answers — just operational metadata used to keep the app
          running and to debug problems.
        </Typography>
      </Box>

      <Box sx={{ mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          What we don't collect
        </Typography>
        <Typography variant="body2">
          We never request or store precise location data. The "Find trials to join" tool, which asks for a condition and a
          general location (city or country) to build a ClinicalTrials.gov search link, runs entirely in your browser —
          what you type there never reaches our servers at all.
        </Typography>
      </Box>

      <Box sx={{ mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Deleting your account
        </Typography>
        <Typography variant="body2">
          Requesting account deletion starts a 7-day grace period, during which you can log back in and cancel it at any
          time. If the grace period passes, your account, conversations, and messages are permanently and irreversibly
          deleted — this is a real deletion, not a soft one.
        </Typography>
      </Box>

      <Button variant="outlined" onClick={() => navigate(-1)}>
        Back
      </Button>
    </Container>
  )
}
