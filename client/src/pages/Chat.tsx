import { useCallback, useEffect, useRef, useState } from 'react'
import { Box, Grid } from '@mui/material'
import ConversationList from '../components/ConversationList'
import MessageList from '../components/MessageList'
import type { Conversation, Message } from '../types'
import InputField, { type InputFieldHandle } from '../components/InputField'
export default function Chat() {
  const BASE_URL = import.meta.env.VITE_BASE_URL

  const toWsBaseUrl = (baseUrl: string) => {
    if (!baseUrl) return baseUrl
    if (baseUrl.startsWith('https://'))
      return baseUrl.replace('https://', 'wss://')
    if (baseUrl.startsWith('http://'))
      return baseUrl.replace('http://', 'ws://')
    return baseUrl
  }

  const [conversations, setConversations] = useState<Conversation[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [nextBefore, setNextBefore] = useState<string | null>(null)
  const [isLoadingOlder, setIsLoadingOlder] = useState(false)
  const [sendStage, setSendStage] = useState<string | null>(null)
  const [selectedConversationId, setSelectedConversationId] = useState<string>('new')
  const [inputValue, setInputValue] = useState<string>('')
  const inputRef = useRef<InputFieldHandle>(null)

  const textToMessage = (text: string): Message => ({
    id: `temp-${Date.now()}`,
    content: text,
    role: 'user',
    timestamp: new Date().toISOString(),
    conversationId:
      selectedConversationId === 'new' ? undefined : selectedConversationId,
    sources: [],
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
      setInputValue('')
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

  const onLogout = useCallback(async () => {
    try {
      await fetch(`${BASE_URL}/auth/logout/`, { method: 'POST', credentials: 'include' })
    } catch (e) {
      console.error('logout failed:', e)
    }
    window.location.href = '/login'
  }, [BASE_URL])

  const onDeleteConversation = useCallback(async (id: string) => {
    try {
      const res = await fetch(`${BASE_URL}/conversations/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (!res.ok) throw new Error(await res.text())
      setConversations((prev) => prev.filter((c) => c.id !== id))
      if (selectedConversationId === id) setSelectedConversationId('new')
    } catch (e) {
      console.error('delete conversation failed:', e)
    }
  }, [BASE_URL, selectedConversationId])

  const onInsertReference = useCallback((id: string) => {
    inputRef.current?.append(`[${id}]`)
  }, [])

  const onMessageSubmit = (e: React.SubmitEvent) => {
    e.preventDefault()
    const messageText = inputValue.trim()
    if (!messageText) return
    setInputValue('')

    const optimisticMessage = textToMessage(messageText)

    // Add optimistic message immediately (functional update avoids stale state)
    setMessages((prev) => [...prev, optimisticMessage])

    // NEW conversation: keep HTTP flow (no WS endpoint for /new yet)
    if (selectedConversationId === 'new') {
      setSendStage('sending')
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
          setMessages((prev) => {
            const withoutTemp = prev.slice(0, -1)
            return [...withoutTemp, ...res.messages]
          })

          setConversations((prev) => [res.conversation, ...prev])
          setSelectedConversationId(res.conversation.id)
          setSendStage(null)
        })
        .catch((e) => {
          console.error('message submit failed:', e)
          setSendStage(null)
        })

      return
    }

    // Existing conversation: WebSocket flow
    const wsBase = toWsBaseUrl(import.meta.env.VITE_BASE_URL)
    const wsUrl = `${wsBase}/conversations/${selectedConversationId}/add_message/ws`

    setSendStage('connecting')

    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      setSendStage('sending')
      ws.send(
        JSON.stringify({
          content: messageText,
          conversation_id: selectedConversationId,
          role: 'user',
        }),
      )
    }

    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data)

        if (data?.type === 'stage') {
          // e.g. 'retrieving_context', 'generating_answer'
          setSendStage(String(data.stage || 'working'))
          return
        }

        if (data?.type === 'final') {
          const res = data
          setMessages((prev) => {
            // Remove optimistic temp message (last item) and append real messages
            const withoutTemp = prev.slice(0, -1)
            return [...withoutTemp, ...(res.messages || [])]
          })

          // Keep conversation list in sync if server returned it
          if (res?.conversation?.id) {
            setConversations((prev) => {
              const idx = prev.findIndex((c) => c.id === res.conversation.id)
              if (idx === -1) return prev
              const updated = [...prev]
              updated[idx] = { ...updated[idx], ...res.conversation }
              return updated
            })
          }

          setSendStage(null)
          ws.close()
          return
        }

        if (data?.type === 'error') {
          console.error('ws error:', data?.message)
          setSendStage(null)
          ws.close()
          return
        }
      } catch (e) {
        console.error('ws message parse failed:', e)
      }
    }

    ws.onerror = (err) => {
      console.error('ws transport error:', err)
      setSendStage(null)
      // fallback is possible, but we keep it simple
      try {
        ws.close()
      } catch (e) {
        console.log(e)
      }
    }

    ws.onclose = () => {
      // If we closed before final, clear stage
      setSendStage((prev) => (prev ? null : prev))
    }
  }

  return (
    <Box className="chat-root">
      <Grid container className="chat-grid" spacing={0}>
        <Grid size={3} className="chat-conversations">
          <ConversationList
            setSelectedConversationId={setSelectedConversationId}
            selectedConversationId={selectedConversationId}
            conversations={conversations}
            onDeleteConversation={onDeleteConversation}
            onLogout={onLogout}
          />
        </Grid>
        <Grid size={9} className="chat-messages">
          <Box className="chat-message-list">
            <MessageList
              messages={messages}
              onLoadOlder={loadOlderMessages}
              hasOlder={!!nextBefore}
              isLoadingOlder={isLoadingOlder}
              sendStage={sendStage}
              onInsertReference={onInsertReference}
            />
          </Box>
          <Box className="chat-input">
            <InputField
                ref={inputRef}
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
