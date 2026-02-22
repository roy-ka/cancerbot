export type AuthButtonsProps = {
  isLogin: boolean
  setIsLogin: (val: boolean) => void
}

export type LoginPayload = {
  email: string
  password: string
  rememberMe: boolean
}

export type RegistrationPayload = {
  email: string
  password: string
  name: string
}

export type Conversation = {
  id: string
  title: string
  lastMessage: string
  lastMessageTime: string
}
export type SourceAndClaim = {
  id: string
  url: string | null
  text: string
  name: string
}

export type Message = {
  id: string | null
  content: string
  conversationId?: string
  role: 'user' | 'assistant'
  timestamp: string
  sources: SourceAndClaim[]
  claims: SourceAndClaim[]
}
