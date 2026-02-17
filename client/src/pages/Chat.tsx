import { Box, Grid } from '@mui/material'
import ConversationList from '../components/ConversationList'
import MessageList from '../components/MessageList'
import { useEffect, useState } from 'react'
import type { Conversation, Message } from '../types'
import InputField from '../components/InputField'
export default function Chat() {
  const BASE_URL = import.meta.env.VITE_BASE_URL

  const [conversations, setConversations] = useState<Conversation[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [selectedConversationId, setSelectedConversationId] =
    useState<string>('new')

  const textToMessage = (text: string): Message => ({
    id: `temp-${Date.now()}`,
    content: text,
    role: 'user',
    timestamp: new Date().toISOString(),
    conversationId:
      selectedConversationId === 'new' ? undefined : selectedConversationId,
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
        return
      }

      try {
        const res = await fetch(
          `${BASE_URL}/conversations/${selectedConversationId}/messages`,
          { credentials: 'include' },
        )
        if (!res.ok) throw new Error(await res.text())

        const { messages, conversation_id } = await res.json()
        if (selectedConversationId === 'new') {
          setConversations((prev) => [conversation_id, ...prev])
        }

        // Replace the message list for the selected conversation
        if (Array.isArray(messages)) {
          setMessages((prev) => (prev === messages ? prev : messages))
        } else if (messages) {
          console.warn('Unexpected messages format 1:', messages)
        } else {
          console.warn('Unexpected messages format 2:', messages)
        }
      } catch (e) {
        console.error('messages failed:', e)
      }
    }
    fetchMessages()
  }, [BASE_URL, selectedConversationId])

  const onMessageSubmit = (e: React.SubmitEvent) => {
    e.preventDefault()
    const form = e.currentTarget
    const messageText = form && form.input ? form.input.value.trim() : ''
    if (!messageText) return

    const optimisticMessage = textToMessage(messageText)
    console.log('optimisticMessage', optimisticMessage)
    // Add optimistic message immediately (functional update avoids stale state)
    setMessages((prev) => [...prev, optimisticMessage])
    const url = `${import.meta.env.VITE_BASE_URL}/conversations/${selectedConversationId === 'new' ? 'new' : `${selectedConversationId}/add_message`}`
    console.log(url)
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
      .catch((error) => console.log(error.detail))
      .then((res) => {
        setMessages((prev) => {
          const withoutTemp = prev.slice(0, -1)
          return [...withoutTemp, ...res.messages]
        })
        if (selectedConversationId === 'new') {
          setConversations((prev) => [res.conversation, ...prev])
          setSelectedConversationId(res.conversation.id)
        }
      })
      .catch((e) => console.error('message submit failed:', e))
  }

  return (
    <Box className="chat-root">
      <Grid container className="chat-grid">
        <Grid size={2} className="chat-conversations">
          <ConversationList
            setSelectedConversationId={setSelectedConversationId}
            selectedConversationId={selectedConversationId}
            conversations={conversations}
          />
        </Grid>
        <Grid container size={10} className="chat-messages" direction="column">
          <Grid size={11} className="chat-message-list">
            <MessageList messages={messages} />
          </Grid>
          <Grid
            size={1}
            className="chat-input"
            sx={{
              justifyContent: 'center',
              alignItems: 'stretch',
              width: '100%',
            }}
          >
            <InputField onSubmit={onMessageSubmit} />
          </Grid>
        </Grid>
      </Grid>
    </Box>
  )
}
