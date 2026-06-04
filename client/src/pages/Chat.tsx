import { useCallback, useEffect, useState } from 'react'
import { Box, Grid } from '@mui/material'
import { useNavigate } from 'react-router-dom'
import ConversationList from '../components/ConversationList'
import MessageList from '../components/MessageList'
import type { Conversation, Message } from '../types'
import InputField from '../components/InputField'
export default function Chat() {
  const BASE_URL = import.meta.env.VITE_BASE_URL
  const navigate = useNavigate()

  const [conversations, setConversations] = useState<Conversation[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [nextBefore, setNextBefore] = useState<string | null>(null)
  const [isLoadingOlder, setIsLoadingOlder] = useState(false)
  const [selectedConversationId, setSelectedConversationId] =
    useState<string>('new')
  const [inputValue, setInputValue] = useState<string>('')
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const setSelectedConversationIdWithClose = (id: string | React.SetStateAction<string>) => {
    setSelectedConversationId(id)
    setSidebarOpen(false)
  }

  const textToMessage = (text: string): Message => ({
    id: `temp-${Date.now()}`,
    content: text,
    role: 'user',
    timestamp: new Date().toISOString(),
    conversationId:
      selectedConversationId === 'new' ? undefined : selectedConversationId,
    sources: [],
    claims: [],
  })

  useEffect(() => {
    if (conversations.length > 0) return

    fetch(`${BASE_URL}/conversations/`, { credentials: 'include' })
      .then(async (res) => {
        if (!res.ok) throw new Error(await res.text())
        const json = await res.json()
        return json?.conversations
      })
      .then(setConversations)
      .catch((e) => {
        console.error('conversations failed:', e)
        if (
          e instanceof Error &&
          e.message.includes('Invalid or expired token')
        ) {
          window.location.href = '/login'
        }
      })
  }, [BASE_URL, conversations.length])

  useEffect(() => {
    const fetchMessages = async () => {
      if (selectedConversationId === 'new') {
        // Avoid re-render loops: only clear if there is something to clear
        setMessages((prev) => (prev.length === 0 ? prev : []))
        setNextBefore(null)
        setIsLoadingOlder(false)
        return
      }

      try {
        const res = await fetch(
          `${BASE_URL}/conversations/${selectedConversationId}/messages/?limit=30`,
          { credentials: 'include' },
        )
        if (!res.ok) throw new Error(await res.text())

        const json = await res.json()
        const apiMessages = json?.messages
        const apiConversation = json?.conversation
        const apiNextBefore = json?.next_before ?? null

        setNextBefore(apiNextBefore)

        // Replace the message list for the selected conversation
        if (Array.isArray(apiMessages)) {
          setMessages((prev) => (prev === apiMessages ? prev : apiMessages))
        } else if (apiMessages) {
          console.warn('Unexpected messages format:', apiMessages)
          setMessages([])
        } else {
          setMessages([])
        }

        // Keep the conversation list in sync (update title/updatedAt) if provided
        if (apiConversation?.id) {
          setConversations((prev) => {
            const idx = prev.findIndex((c) => c.id === apiConversation.id)
            if (idx === -1) return prev
            const updated = [...prev]
            updated[idx] = { ...updated[idx], ...apiConversation }
            return updated
          })
        }
      } catch (e) {
        console.error('messages failed:', e)
      }
    }
    fetchMessages()
  }, [BASE_URL, selectedConversationId])

  const loadOlderMessages = useCallback(async (): Promise<boolean> => {
    // No selected conversation or no cursor means no older messages
    if (selectedConversationId === 'new') return false
    if (!nextBefore) return false
    if (isLoadingOlder) return true

    setIsLoadingOlder(true)
    try {
      const res = await fetch(
        `${BASE_URL}/conversations/${selectedConversationId}/messages/?limit=30&before=${encodeURIComponent(nextBefore)}`,
        { credentials: 'include' },
      )
      if (!res.ok) throw new Error(await res.text())

      const json = await res.json()
      const older = Array.isArray(json?.messages)
        ? (json.messages as Message[])
        : []
      const newCursor = json?.next_before ?? null

      // Update cursor first
      setNextBefore(newCursor)

      if (older.length === 0) {
        return false
      }

      // Prepend older messages, avoiding duplicates by id
      setMessages((prev) => {
        const seen = new Set(prev.map((m) => m.id))
        const toAdd = older.filter((m) => !seen.has(m.id))
        return [...toAdd, ...prev]
      })

      return true
    } catch (e) {
      console.error('load older messages failed:', e)
      return false
    } finally {
      setIsLoadingOlder(false)
    }
  }, [BASE_URL, selectedConversationId, nextBefore, isLoadingOlder])

  const handleLogout = async () => {
    try {
      const res = await fetch(`${BASE_URL}/auth/logout/`, {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) throw new Error(await res.text())
      localStorage.removeItem('termsAccepted')
      navigate('/login')
    } catch (e) {
      console.error('logout failed:', e)
    }
  }

  const onMessageSubmit = (e: React.SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    const messageText = inputValue.trim()
    if (!messageText) return

    const optimisticMessage = textToMessage(messageText)

    // Add optimistic message immediately
    setMessages((prev) => [...prev, optimisticMessage])
    setInputValue('')

    // For new conversations, create first then send message
    if (selectedConversationId === 'new') {
      const url = `${import.meta.env.VITE_BASE_URL}/conversations/new`
      fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(optimisticMessage),
      })
        .then(async (res) => {
          if (!res.ok) throw new Error(await res.text())
          return res.json()
        })
        .then((res) => {
          if (!res) return
          setMessages((prev) => {
            const withoutTemp = prev.slice(0, -1)
            return [...withoutTemp, ...res.messages]
          })
          setConversations((prev) => [res.conversation, ...prev])
          setSelectedConversationId(res.conversation.id)
        })
        .catch((e) => console.error('new conversation failed:', e))
    } else {
      // Use WebSocket for existing conversations
      connectAndSendMessage(selectedConversationId, optimisticMessage)
    }
  }

  const connectAndSendMessage = (conversationId: string, message: any) => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${wsProtocol}//${window.location.host}${import.meta.env.VITE_BASE_URL}/conversations/${conversationId}/add_message/ws`

    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      console.log('[ws] Connected, sending message...')
      ws.send(JSON.stringify(message))
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        console.log('[ws] Status:', data.status)

        switch (data.status) {
          case 'loading':
            console.log('[ws] Loading...')
            break
          case 'saving_user_message':
            console.log('[ws] Saving user message...')
            break
          case 'retrieving_context':
            console.log('[ws] Retrieving context from OpenSearch...')
            break
          case 'generating_answer':
            console.log('[ws] Generating answer with LLM...')
            break
          case 'done':
            console.log('[ws] Done! Received messages:', data.messages)
            setMessages((prev) => {
              const withoutTemp = prev.slice(0, -1)
              return [...withoutTemp, ...data.messages]
            })
            if (data.conversation) {
              setConversations((prev) => {
                const idx = prev.findIndex((c) => c.id === data.conversation.id)
                if (idx === -1) {
                  return [data.conversation, ...prev]
                }
                const updated = [...prev]
                updated[idx] = data.conversation
                return updated
              })
            }
            ws.close()
            break
          case 'error':
            console.error('[ws] Error:', data.detail)
            ws.close(1000)
            break
        }
      } catch (e) {
        console.error('[ws] Failed to parse message:', e)
      }
    }

    ws.onerror = (event) => {
      console.error('[ws] Error:', event)
      setMessages((prev) => {
        const withoutTemp = prev.slice(0, -1)
        return withoutTemp
      })
    }

    ws.onclose = () => {
      console.log('[ws] Connection closed')
    }
  }

  return (
    <Box className={`chat-root ${sidebarOpen ? 'sidebar-open' : ''}`}>
      <button
        className="chat-sidebar-toggle"
        onClick={() => setSidebarOpen(!sidebarOpen)}
        aria-label="Toggle conversations"
      >
        ☰
      </button>
      {sidebarOpen && (
        <div
          className="chat-sidebar-backdrop"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <Grid container className="chat-grid" spacing={0}>
        <Grid
          size={3}
          className={`chat-conversations ${sidebarOpen ? 'open' : ''}`}
        >
          <ConversationList
            setSelectedConversationId={setSelectedConversationIdWithClose}
            selectedConversationId={selectedConversationId}
            conversations={conversations}
            onLogout={handleLogout}
            onCloseSidebar={() => setSidebarOpen(false)}
          />
        </Grid>
        <Grid size={9} className="chat-messages">
          <Box className="chat-message-list">
            <MessageList
              messages={messages}
              onLoadOlder={loadOlderMessages}
              hasOlder={!!nextBefore}
              isLoadingOlder={isLoadingOlder}
            />
          </Box>
          <Box className="chat-input">
            <InputField
              onSubmit={onMessageSubmit}
              value={inputValue}
              onChange={setInputValue}
            />
          </Box>
        </Grid>
      </Grid>
    </Box>
  )
}
