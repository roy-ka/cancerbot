import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Alert, Box, CircularProgress, Container, Typography } from '@mui/material'
import MessageItem from '../components/MessageItem'
import type { Message } from '../types'

const BASE_URL = import.meta.env.VITE_BASE_URL || ''

export default function SharedConversation() {
  const { token } = useParams<{ token: string }>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [messages, setMessages] = useState<Message[]>([])

  useEffect(() => {
    if (!token) return
    fetch(`${BASE_URL}/shared/${token}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(res.status === 404 ? 'not_found' : 'failed')
        return res.json()
      })
      .then((data) => {
        setTitle(data?.conversation?.title || 'Shared conversation')
        setMessages(Array.isArray(data?.messages) ? data.messages : [])
      })
      .catch((e) => {
        setError(e instanceof Error && e.message === 'not_found' ? 'not_found' : 'failed')
      })
      .finally(() => setLoading(false))
  }, [token])

  if (loading) {
    return (
      <Container maxWidth="md" sx={{ py: 4, display: 'flex', justifyContent: 'center' }}>
        <CircularProgress size={24} />
      </Container>
    )
  }

  if (error) {
    return (
      <Container maxWidth="md" sx={{ py: 4 }}>
        <Alert severity="error">
          {error === 'not_found'
            ? 'This share link is invalid or has been revoked.'
            : 'Something went wrong loading this conversation.'}
        </Alert>
      </Container>
    )
  }

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h4" component="h1" gutterBottom>
          {title}
        </Typography>
        <Typography variant="body2" color="textSecondary">
          A shared, read-only CancerBot conversation.
        </Typography>
      </Box>

      <Box>
        {messages.map((message) => (
          <MessageItem key={message.id} message={message} />
        ))}
      </Box>
    </Container>
  )
}
