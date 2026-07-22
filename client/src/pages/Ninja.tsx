import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  List,
  ListItemButton,
  ListItemText,
  Snackbar,
  TextField,
  Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import MessageItem from '../components/MessageItem'
import type { Source } from '../types'

type NinjaUser = {
  id: string
  name: string | null
  email: string
  created_at: string | null
}

type NinjaConversation = {
  id: string
  title: string | null
  updatedAt: string | null
  lastMessage: string | null
}

type NinjaMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string | null
  hidden_from_user: boolean
  sources: Source[]
}

const BASE_URL = import.meta.env.VITE_BASE_URL || ''

export default function Ninja() {
  const navigate = useNavigate()

  const [accessChecked, setAccessChecked] = useState(false)
  const [users, setUsers] = useState<NinjaUser[]>([])
  const [selectedUser, setSelectedUser] = useState<NinjaUser | null>(null)
  const [conversations, setConversations] = useState<NinjaConversation[]>([])
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<NinjaMessage[]>([])
  const [inputValue, setInputValue] = useState('')
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  // Gate access — only ninja accounts may view this page.
  useEffect(() => {
    fetch(`${BASE_URL}/auth/check/`, { credentials: 'include' })
      .then(async (res) => {
        if (!res.ok) throw new Error('not authenticated')
        return res.json()
      })
      .then((data) => {
        if (!data.is_ninja) {
          navigate('/chat', { replace: true })
          return
        }
        setAccessChecked(true)
      })
      .catch(() => navigate('/login', { replace: true }))
  }, [navigate])

  useEffect(() => {
    if (!accessChecked) return
    setLoading(true)
    fetch(`${BASE_URL}/ninja/users/`, { credentials: 'include' })
      .then(async (res) => {
        if (!res.ok) throw new Error(await res.text())
        return res.json()
      })
      .then((data) => setUsers(data.users || []))
      .catch(() => setErrorMsg('Failed to load users.'))
      .finally(() => setLoading(false))
  }, [accessChecked])

  const openUser = (user: NinjaUser) => {
    setSelectedUser(user)
    setSelectedConversationId(null)
    setMessages([])
    setLoading(true)
    fetch(`${BASE_URL}/ninja/users/${user.id}/conversations/`, { credentials: 'include' })
      .then(async (res) => {
        if (!res.ok) throw new Error(await res.text())
        return res.json()
      })
      .then((data) => setConversations(data.conversations || []))
      .catch(() => setErrorMsg('Failed to load conversations.'))
      .finally(() => setLoading(false))
  }

  const loadMessages = (conversationId: string) => {
    setLoading(true)
    fetch(`${BASE_URL}/ninja/conversations/${conversationId}/messages/`, { credentials: 'include' })
      .then(async (res) => {
        if (!res.ok) throw new Error(await res.text())
        return res.json()
      })
      .then((data) => setMessages(data.messages || []))
      .catch(() => setErrorMsg('Failed to load messages.'))
      .finally(() => setLoading(false))
  }

  const openConversation = (conversationId: string) => {
    setSelectedConversationId(conversationId)
    loadMessages(conversationId)
  }

  const sendMessage = async () => {
    if (!inputValue.trim() || !selectedConversationId) return
    setSending(true)
    try {
      const res = await fetch(
        `${BASE_URL}/ninja/conversations/${selectedConversationId}/add_message`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: inputValue }),
        },
      )
      if (!res.ok) throw new Error(await res.text())
      setInputValue('')
      loadMessages(selectedConversationId)
    } catch {
      setErrorMsg('Failed to send message.')
    } finally {
      setSending(false)
    }
  }

  if (!accessChecked) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <CircularProgress size={28} />
      </Box>
    )
  }

  return (
    <Box sx={{ minHeight: '100vh', p: { xs: 2, sm: 4 }, maxWidth: 900, mx: 'auto' }}>
      <Snackbar
        open={!!errorMsg}
        autoHideDuration={5000}
        onClose={() => setErrorMsg(null)}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Alert severity="error" onClose={() => setErrorMsg(null)}>{errorMsg}</Alert>
      </Snackbar>

      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 3 }}>
        <Typography variant="h5">🥷 Ninja</Typography>
        <Button startIcon={<ArrowBackIcon />} onClick={() => navigate('/chat')} sx={{ textTransform: 'none' }}>
          Back to Chat
        </Button>
      </Box>

      {/* Breadcrumb-ish step indicator */}
      <Typography variant="body2" sx={{ opacity: 0.7, mb: 2 }}>
        Users
        {selectedUser && <> → {selectedUser.email}</>}
        {selectedConversationId && <> → Conversation</>}
      </Typography>

      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress size={24} />
        </Box>
      )}

      {!loading && !selectedUser && (
        <List>
          {users.map((u) => (
            <ListItemButton key={u.id} onClick={() => openUser(u)} sx={{ borderRadius: 2, mb: 0.5 }}>
              <ListItemText primary={u.name || u.email} secondary={u.email} />
            </ListItemButton>
          ))}
          {users.length === 0 && (
            <Typography sx={{ opacity: 0.6, py: 2 }}>No users found.</Typography>
          )}
        </List>
      )}

      {!loading && selectedUser && !selectedConversationId && (
        <>
          <Button
            size="small"
            startIcon={<ArrowBackIcon />}
            onClick={() => { setSelectedUser(null); setConversations([]) }}
            sx={{ textTransform: 'none', mb: 1 }}
          >
            All users
          </Button>
          <List>
            {conversations.map((c) => (
              <ListItemButton key={c.id} onClick={() => openConversation(c.id)} sx={{ borderRadius: 2, mb: 0.5 }}>
                <ListItemText
                  primary={c.title || 'Untitled conversation'}
                  secondary={c.lastMessage}
                />
              </ListItemButton>
            ))}
            {conversations.length === 0 && (
              <Typography sx={{ opacity: 0.6, py: 2 }}>This user has no conversations.</Typography>
            )}
          </List>
        </>
      )}

      {!loading && selectedConversationId && (
        <>
          <Button
            size="small"
            startIcon={<ArrowBackIcon />}
            onClick={() => { setSelectedConversationId(null); setMessages([]) }}
            sx={{ textTransform: 'none', mb: 1 }}
          >
            {selectedUser?.email}'s conversations
          </Button>

          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, mb: 2 }}>
            {messages.map((m) => (
              <Box
                key={m.id}
                sx={{
                  borderRadius: 2,
                  border: m.hidden_from_user ? '1px dashed rgba(255,180,0,0.5)' : '1px solid transparent',
                  py: 0.5,
                }}
              >
                <Box
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1,
                    justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start',
                    px: 2,
                  }}
                >
                  <Typography variant="caption" sx={{ opacity: 0.6, fontWeight: 700 }}>
                    {m.role === 'user' ? 'User' : 'Assistant'}
                  </Typography>
                  {m.hidden_from_user && (
                    <Chip label="🥷 hidden from user" size="small" sx={{ height: 20, fontSize: '0.7rem' }} />
                  )}
                </Box>
                <MessageItem
                  message={{
                    id: m.id,
                    content: m.content,
                    role: m.role,
                    timestamp: m.created_at || '',
                    sources: m.sources || [],
                  }}
                />
              </Box>
            ))}
            {messages.length === 0 && (
              <Typography sx={{ opacity: 0.6, py: 2 }}>No messages yet.</Typography>
            )}
          </Box>

          <Box sx={{ display: 'flex', gap: 1 }}>
            <TextField
              fullWidth
              size="small"
              placeholder="Ask a question in this conversation (hidden from the real user)…"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() } }}
              disabled={sending}
            />
            <Button variant="contained" onClick={sendMessage} disabled={sending || !inputValue.trim()}>
              {sending ? '…' : 'Send'}
            </Button>
          </Box>
        </>
      )}
    </Box>
  )
}
