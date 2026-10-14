import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Snackbar,
  FormControlLabel,
  Switch,
  Typography,
  IconButton,
  Menu,
  MenuItem,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  CircularProgress,
  TextField,
} from '@mui/material'
import FileDownloadOutlinedIcon from '@mui/icons-material/FileDownloadOutlined'
import TranslateIcon from '@mui/icons-material/Translate'
import SummarizeOutlinedIcon from '@mui/icons-material/SummarizeOutlined'
import ShareOutlinedIcon from '@mui/icons-material/ShareOutlined'
import { useNavigate } from 'react-router-dom'
import ConversationList from '../components/ConversationList'
import MessageList from '../components/MessageList'
import type { Conversation, Message } from '../types'
import InputField, { type InputFieldHandle } from '../components/InputField'
import IconGuideDialog from '../components/IconGuideDialog'
import { extractUrls } from '../utils/urls'
import { isPendingDeletionResponse, loginPathForAuthFailure } from '../utils/authRedirect'
import { conversationToMarkdown, downloadMarkdown, printConversationAsPdf } from '../utils/conversationExport'
import { openConversationInGoogleTranslate } from '../utils/googleTranslate'
import { mergeFetchedMessages } from '../utils/mergeFetchedMessages'
export default function Chat() {
  const BASE_URL = import.meta.env.VITE_BASE_URL || ''
  const navigate = useNavigate()

  const [conversations, setConversations] = useState<Conversation[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [nextBefore, setNextBefore] = useState<string | null>(null)
  const [isLoadingOlder, setIsLoadingOlder] = useState(false)
  const [selectedConversationId, setSelectedConversationId] =
    useState<string>('new')
  const [inputValue, setInputValue] = useState<string>('')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [currentStage, setCurrentStage] = useState<string | null>(null)
  const [streamingContent, setStreamingContent] = useState<string | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [hasProfile, setHasProfile] = useState(false)
  const [useProfileContextEnabled, setUseProfileContextEnabled] = useState(true)
  const [exportMenuAnchor, setExportMenuAnchor] = useState<HTMLElement | null>(null)
  const [summaryDialogOpen, setSummaryDialogOpen] = useState(false)
  const [summaryText, setSummaryText] = useState('')
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [summaryError, setSummaryError] = useState('')
  const [summaryCopied, setSummaryCopied] = useState(false)
  const [conversationShared, setConversationShared] = useState(false)
  const [shareDialogOpen, setShareDialogOpen] = useState(false)
  const [shareUrl, setShareUrl] = useState('')
  const [shareLoading, setShareLoading] = useState(false)
  const [shareError, setShareError] = useState('')
  const [shareCopied, setShareCopied] = useState(false)
  // Icon tutorial. Shown while the user has no conversations yet; `loaded`
  // gates it on the conversations fetch having actually returned, so an
  // existing user doesn't see it flash during the initial request.
  const [conversationsLoaded, setConversationsLoaded] = useState(false)
  const [guideManuallyOpen, setGuideManuallyOpen] = useState(false)
  const [guideDismissed, setGuideDismissed] = useState(false)

  // Prevent body-level scroll so the chat layout fills the viewport exactly
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  // The per-conversation toggle only makes sense (and is only shown) when
  // there's an actual populated profile to include or exclude.
  useEffect(() => {
    fetch(`${BASE_URL}/profile/me`, { credentials: 'include' })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data?.exists) return
        const populated = !!(
          data.cancer_type || data.stage || data.biomarkers || data.age_band || data.treatment_status
        )
        setHasProfile(populated)
      })
      .catch(() => setHasProfile(false))
  }, [BASE_URL])
  // When a new conversation is created and the WS is in-flight, skip the
  // message fetch triggered by setSelectedConversationId so the optimistic
  // message is not wiped before the WS final response arrives.
  const skipFetchForConvRef = useRef<string | null>(null)
  // What's on screen right now, so a conversation load can tell which
  // messages were added after it started (see mergeFetchedMessages).
  const messagesRef = useRef<Message[]>([])
  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  // Set once the user picks or starts a conversation; from then on the
  // initial conversation-list load must not move the selection.
  const userChoseConversationRef = useRef(false)

  const setSelectedConversationIdWithClose = (id: string | React.SetStateAction<string>) => {
    userChoseConversationRef.current = true
    setSelectedConversationId(id)
    setSidebarOpen(false)
  }

  const textToMessage = (text: string): Message => {
    const urls = extractUrls(text)
    return {
      id: `temp-${Date.now()}`,
      content: text,
      role: 'user',
      timestamp: new Date().toISOString(),
      conversationId:
        selectedConversationId === 'new' ? undefined : selectedConversationId,
      sources: [],
      ...(urls.length > 0 && { urls }),
    }
  }

  useEffect(() => {
    if (conversations.length > 0) return

    fetch(`${BASE_URL}/conversations/`, { credentials: 'include' })
      .then(async (res) => {
        if (!res.ok) {
          if (res.status === 401) {
            window.location.href = loginPathForAuthFailure(await isPendingDeletionResponse(res))
            return null
          }
          throw new Error(await res.text())
        }
        const json = await res.json()
        return json?.conversations
      })
      .then((convs: Conversation[] | null) => {
        if (!convs) return
        // Keep conversations created locally while this request was in
        // flight (e.g. by a message sent from the new-conversation screen).
        setConversations((prev) => {
          const fetchedIds = new Set(convs.map((c) => c.id))
          return [...prev.filter((c) => !fetchedIds.has(c.id)), ...convs]
        })
        setConversationsLoaded(true)
        if (Array.isArray(convs) && convs.length > 0 && !userChoseConversationRef.current) {
          setSelectedConversationId(convs[0].id)
        }
      })
      .catch((e) => {
        setConversationsLoaded(true)
        console.error('conversations failed:', e)
      })
  }, [BASE_URL, conversations.length])

  useEffect(() => {
    // Set by the cleanup when the selection changes, so a slower load for a
    // conversation the user already left can't overwrite the current one.
    let cancelled = false
    const fetchMessages = async () => {
      if (selectedConversationId === 'new') {
        // Avoid re-render loops: only clear if there is something to clear
        setMessages((prev) => (prev.length === 0 ? prev : []))
        setNextBefore(null)
        setIsLoadingOlder(false)
        setUseProfileContextEnabled(true)
        return
      }

      // Skip fetch for a newly-created conversation while the WS is in-flight
      if (skipFetchForConvRef.current === selectedConversationId) {
        skipFetchForConvRef.current = null
        return
      }

      const onScreenAtStart = messagesRef.current
      try {
        const res = await fetch(
          `${BASE_URL}/conversations/${selectedConversationId}/messages/?limit=30`,
          { credentials: 'include' },
        )
        if (!res.ok) throw new Error(await res.text())

        const json = await res.json()
        if (cancelled) return
        const apiMessages = json?.messages
        const apiConversation = json?.conversation
        const apiNextBefore = json?.next_before ?? null

        setNextBefore(apiNextBefore)

        // Replace the message list for the selected conversation
        if (Array.isArray(apiMessages)) {
          setMessages((prev) => mergeFetchedMessages(prev, apiMessages, onScreenAtStart))
        } else if (apiMessages) {
  
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
        if (typeof apiConversation?.use_profile_context === 'boolean') {
          setUseProfileContextEnabled(apiConversation.use_profile_context)
        }
        if (typeof apiConversation?.shared === 'boolean') {
          setConversationShared(apiConversation.shared)
        }
      } catch (e) {
        console.error('messages failed:', e)
      }
    }
    fetchMessages()
    return () => {
      cancelled = true
    }
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

  const handleDeleteConversation = async (id: string): Promise<void> => {
    try {
      const res = await fetch(`${BASE_URL}/conversations/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (!res.ok) return
      setConversations((prev) => prev.filter((c) => c.id !== id))
      if (selectedConversationId === id) setSelectedConversationId('new')
    } catch (e) {
      console.error('delete conversation failed:', e)
    }
  }

  const handleSplitConversation = (conversation: {
    id: string
    title: string
    lastMessage: string | null
    lastMessageTime: string | null
  }) => {
    setConversations((prev) => [
      {
        id: conversation.id,
        title: conversation.title,
        lastMessage: conversation.lastMessage ?? '',
        lastMessageTime: conversation.lastMessageTime ?? '',
      },
      ...prev,
    ])
    userChoseConversationRef.current = true
    setSelectedConversationId(conversation.id)
  }

  const handleDeleteAccount = async (): Promise<string | null> => {
    try {
      const res = await fetch(`${BASE_URL}/auth/request-delete/`, {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) return 'Something went wrong. Please try again.'
      return null
    } catch {
      return 'Connection error. Please try again.'
    }
  }

  const handleChangeEmail = async (): Promise<string | null> => {
    try {
      const res = await fetch(`${BASE_URL}/auth/request-email-change/`, {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        return data?.detail ?? 'Something went wrong. Please try again.'
      }
      return null
    } catch {
      return 'Connection error. Please try again.'
    }
  }

  const sendViaWebSocket = (conversationId: string, message: Message) => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsHost = BASE_URL ? new URL(BASE_URL).host : window.location.host
    const wsUrl = `${protocol}//${wsHost}/conversations/${conversationId}/add_message/ws`

    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      ws.send(JSON.stringify(message))
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)

        if (msg.type === 'stage') {
          // streamingContent stays null (not '') here — MessageList shows the
          // stage indicator ("Generating answer...") whenever streamingContent
          // is null and only switches to the token bubble once one exists, so
          // setting it eagerly on this stage hid the indicator before any
          // token had actually arrived.
          setCurrentStage(msg.stage)
        } else if (msg.type === 'token') {
          setStreamingContent((prev) => (prev ?? '') + msg.token)
        } else if (msg.type === 'final') {
          setStreamingContent(null)
          setCurrentStage(null)
          setMessages((prev) => {
            const withoutTemp = prev.slice(0, -1)
            return [...withoutTemp, ...msg.messages]
          })
          if (msg.conversation?.id) {
            setConversations((prev) => {
              const idx = prev.findIndex((c) => c.id === msg.conversation.id)
              if (idx === -1) return prev
              const merged = { ...prev[idx], ...msg.conversation }
              return [merged, ...prev.filter((_, i) => i !== idx)]
            })
          }
          if (typeof msg.conversation?.use_profile_context === 'boolean') {
            setUseProfileContextEnabled(msg.conversation.use_profile_context)
          }
          ws.close()
        } else if (msg.type === 'error') {
          setStreamingContent(null)
          setCurrentStage(null)
          setMessages((prev) => prev.filter((m) => !m.id?.startsWith('temp-')))
          setErrorMsg(msg.message || 'An error occurred. Please try again.')
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e)
      }
    }

    ws.onerror = () => {
      setStreamingContent(null)
      setCurrentStage(null)
      setMessages((prev) => prev.filter((m) => !m.id?.startsWith('temp-')))

      // The WS handshake goes through the same get_current_user dependency
      // as every REST route, so it's rejected the same way when deletion
      // was scheduled from another device — but a WebSocket close carries
      // no response body to read the reason from. Ask /auth/check/ (a
      // plain REST call) instead of showing a generic error that would
      // otherwise be this path's only outcome for that case.
      fetch(`${BASE_URL}/auth/check/`, { credentials: 'include' })
        .then(async (res) => {
          if (!res.ok && (await isPendingDeletionResponse(res))) {
            window.location.href = loginPathForAuthFailure(true)
            return
          }
          setErrorMsg('Connection error. Please try again.')
        })
        .catch(() => setErrorMsg('Connection error. Please try again.'))
    }

    ws.onclose = () => {
      console.debug('WebSocket closed')
    }
  }

  const handleToggleProfileContext = () => {
    if (!selectedConversationId || selectedConversationId === 'new') return
    const next = !useProfileContextEnabled
    setUseProfileContextEnabled(next) // optimistic
    fetch(`${BASE_URL}/conversations/${selectedConversationId}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ use_profile_context: next }),
    })
      .then((res) => {
        if (!res.ok) setUseProfileContextEnabled(!next)
      })
      .catch(() => setUseProfileContextEnabled(!next)) // revert on failure
  }

  const currentConversationTitle =
    conversations.find((c) => c.id === selectedConversationId)?.title || 'Conversation'

  const handleExportMarkdown = () => {
    setExportMenuAnchor(null)
    downloadMarkdown(
      `${currentConversationTitle}.md`,
      conversationToMarkdown(currentConversationTitle, messages),
    )
  }

  const handleTranslateConversation = () => {
    openConversationInGoogleTranslate(messages)
  }

  const handleSummarizeConversation = async () => {
    if (selectedConversationId === 'new') return
    setSummaryDialogOpen(true)
    setSummaryLoading(true)
    setSummaryError('')
    setSummaryText('')
    setSummaryCopied(false)
    try {
      const res = await fetch(`${BASE_URL}/conversations/${selectedConversationId}/summarize`, {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      setSummaryText(data.summary)
    } catch {
      setSummaryError('Failed to summarize this conversation. Please try again.')
    } finally {
      setSummaryLoading(false)
    }
  }

  const handleCopySummary = async () => {
    try {
      await navigator.clipboard.writeText(summaryText)
      setSummaryCopied(true)
    } catch {
      setSummaryCopied(false)
    }
  }

  const handleExportPdf = () => {
    setExportMenuAnchor(null)
    printConversationAsPdf(currentConversationTitle, messages)
  }

  const handleOpenShareDialog = async () => {
    if (selectedConversationId === 'new') return
    setShareDialogOpen(true)
    setShareLoading(true)
    setShareError('')
    setShareCopied(false)
    try {
      const res = await fetch(`${BASE_URL}/conversations/${selectedConversationId}/share`, {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      setShareUrl(data.share_url)
      setConversationShared(true)
    } catch {
      setShareError('Failed to create a share link. Please try again.')
    } finally {
      setShareLoading(false)
    }
  }

  const handleCopyShareUrl = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl)
      setShareCopied(true)
    } catch {
      setShareCopied(false)
    }
  }

  const handleStopSharing = async () => {
    if (selectedConversationId === 'new') return
    setShareLoading(true)
    setShareError('')
    try {
      const res = await fetch(`${BASE_URL}/conversations/${selectedConversationId}/share`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (!res.ok) throw new Error(await res.text())
      setConversationShared(false)
      setShareUrl('')
      setShareDialogOpen(false)
    } catch {
      setShareError('Failed to stop sharing. Please try again.')
    } finally {
      setShareLoading(false)
    }
  }

  const inputFieldRef = useRef<InputFieldHandle>(null)

  // From a citation's popover: put the source's id in the message box (the
  // backend fetches that source by id and answers from it), then focus it.
  const handleAskAboutSource = useCallback((sourceId: string) => {
    inputFieldRef.current?.append(`[${sourceId}] `)
    // Deferred: the popover's focus trap is still active during this click
    // and would pull focus straight back until the popover has closed.
    setTimeout(() => inputFieldRef.current?.focus(), 0)
  }, [])

  const onMessageSubmit = (e: React.SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    const messageText = inputValue.trim()
    if (!messageText) return
    userChoseConversationRef.current = true

    const optimisticMessage = textToMessage(messageText)
    setMessages((prev) => [...prev, optimisticMessage])
    setInputValue('')

    if (selectedConversationId === 'new') {
      setCurrentStage('loading_conversation')
      fetch(`${BASE_URL}/conversations/create/`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: messageText.slice(0, 20) }),
      })
        .then(async (res) => {
          if (!res.ok) {
            // Same pending-deletion case sendViaWebSocket's ws.onerror
            // handles below — this is the other path a first message can
            // take (starting a brand-new conversation goes through this
            // plain REST call instead of straight to the WebSocket), so it
            // needs the same explained redirect rather than a generic error.
            if (await isPendingDeletionResponse(res)) {
              window.location.href = loginPathForAuthFailure(true)
              return null
            }
            throw new Error(await res.text())
          }
          return res.json()
        })
        .then((conv) => {
          if (!conv) return
          skipFetchForConvRef.current = conv.id
          setConversations((prev) => [conv, ...prev])
          setSelectedConversationId(conv.id)
          sendViaWebSocket(conv.id, { ...optimisticMessage, conversationId: conv.id })
        })
        .catch(() => {
          setCurrentStage(null)
          setMessages((prev) => prev.filter((m) => !m.id?.startsWith('temp-')))
          setErrorMsg('Failed to send message. Please try again.')
        })
    } else {
      sendViaWebSocket(selectedConversationId, optimisticMessage)
    }
  }

  // Derived, not stored: computing this avoids setting state from an effect
  // just to mirror data we already have.
  const guideOpen =
    guideManuallyOpen ||
    (conversationsLoaded && conversations.length === 0 && !guideDismissed)

  const closeGuide = () => {
    setGuideManuallyOpen(false)
    setGuideDismissed(true)
  }

  return (
    <Box className={`chat-root ${sidebarOpen ? 'sidebar-open' : ''}`}>
      <Snackbar
        open={!!errorMsg}
        autoHideDuration={6000}
        onClose={() => setErrorMsg(null)}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Alert severity="error" onClose={() => setErrorMsg(null)} sx={{ width: '100%' }}>
          {errorMsg}
        </Alert>
      </Snackbar>
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
      <Box className="chat-body">
        <Box className={`chat-conversations ${sidebarOpen ? 'open' : ''}`}>
          <ConversationList
            setSelectedConversationId={setSelectedConversationIdWithClose}
            selectedConversationId={selectedConversationId}
            conversations={conversations}
            onLogout={handleLogout}
            onDeleteAccount={handleDeleteAccount}
            onChangeEmail={handleChangeEmail}
            onDeleteConversation={handleDeleteConversation}
            onCloseSidebar={() => setSidebarOpen(false)}
            onOpenGuide={() => setGuideManuallyOpen(true)}
          />
        </Box>
        <Box className="chat-messages">
          {selectedConversationId !== 'new' && (
            <Box sx={{ px: 2, pt: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
              {hasProfile && (
                <FormControlLabel
                  control={
                    <Switch
                      size="small"
                      checked={useProfileContextEnabled}
                      onChange={handleToggleProfileContext}
                    />
                  }
                  label={
                    <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.6)' }}>
                      Using your health profile for this conversation
                    </Typography>
                  }
                />
              )}
              <Tooltip title="Export conversation">
                <IconButton
                  onClick={(e) => setExportMenuAnchor(e.currentTarget)}
                  sx={{ color: 'rgba(255,255,255,0.6)' }}
                >
                  <FileDownloadOutlinedIcon fontSize="medium" />
                </IconButton>
              </Tooltip>
              <Menu
                anchorEl={exportMenuAnchor}
                open={Boolean(exportMenuAnchor)}
                onClose={() => setExportMenuAnchor(null)}
              >
                <MenuItem onClick={handleExportMarkdown}>Download as Markdown</MenuItem>
                <MenuItem onClick={handleExportPdf}>Download as PDF</MenuItem>
              </Menu>
              <Tooltip title="Translate conversation">
                <IconButton
                  onClick={handleTranslateConversation}
                  sx={{ color: 'rgba(255,255,255,0.6)' }}
                >
                  <TranslateIcon fontSize="medium" />
                </IconButton>
              </Tooltip>
              <Tooltip title="Summarize conversation">
                <IconButton
                  onClick={handleSummarizeConversation}
                  sx={{ color: 'rgba(255,255,255,0.6)' }}
                >
                  <SummarizeOutlinedIcon fontSize="medium" />
                </IconButton>
              </Tooltip>
              <Tooltip title="Share conversation">
                <IconButton
                  onClick={handleOpenShareDialog}
                  sx={{ color: conversationShared ? 'rgba(47, 227, 198, 0.9)' : 'rgba(255,255,255,0.6)' }}
                >
                  <ShareOutlinedIcon fontSize="medium" />
                </IconButton>
              </Tooltip>
            </Box>
          )}
          <Box className="chat-message-list">
            <MessageList
              messages={messages}
              onLoadOlder={loadOlderMessages}
              hasOlder={!!nextBefore}
              isLoadingOlder={isLoadingOlder}
              currentStage={currentStage}
              streamingContent={streamingContent}
              onExampleClick={setInputValue}
              conversationId={selectedConversationId === 'new' ? undefined : selectedConversationId}
              onSplit={handleSplitConversation}
              onAskAboutSource={handleAskAboutSource}
            />
          </Box>
        </Box>
      </Box>
      <Box className="chat-input">
        <InputField
          ref={inputFieldRef}
          onSubmit={onMessageSubmit}
          value={inputValue}
          onChange={setInputValue}
        />
      </Box>
      <IconGuideDialog open={guideOpen} onClose={closeGuide} />
      <Dialog
        open={summaryDialogOpen}
        onClose={() => setSummaryDialogOpen(false)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Conversation Summary</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {summaryLoading && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 2 }}>
              <CircularProgress size={20} />
              <Typography variant="body2">Summarizing...</Typography>
            </Box>
          )}
          {summaryError && <Alert severity="error">{summaryError}</Alert>}
          {!summaryLoading && !summaryError && summaryText && (
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
              {summaryText}
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          {!summaryLoading && summaryText && (
            <Button onClick={handleCopySummary}>{summaryCopied ? 'Copied!' : 'Copy'}</Button>
          )}
          <Button onClick={() => setSummaryDialogOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>
      <Dialog
        open={shareDialogOpen}
        onClose={() => setShareDialogOpen(false)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Share Conversation</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          <Typography variant="body2" color="textSecondary">
            Anyone with this link can view a read-only copy of this conversation. They won't need to log in.
          </Typography>
          {shareLoading && !shareUrl && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 2 }}>
              <CircularProgress size={20} />
              <Typography variant="body2">Creating link...</Typography>
            </Box>
          )}
          {shareError && <Alert severity="error">{shareError}</Alert>}
          {shareUrl && (
            <TextField
              value={shareUrl}
              fullWidth
              size="small"
              slotProps={{ input: { readOnly: true } }}
              onFocus={(e) => e.target.select()}
            />
          )}
        </DialogContent>
        <DialogActions>
          {shareUrl && (
            <Button onClick={handleStopSharing} color="error" disabled={shareLoading}>
              Stop sharing
            </Button>
          )}
          {shareUrl && (
            <Button onClick={handleCopyShareUrl}>{shareCopied ? 'Copied!' : 'Copy link'}</Button>
          )}
          <Button onClick={() => setShareDialogOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
