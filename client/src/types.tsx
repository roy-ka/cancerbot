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
  first_name: string
  last_name: string
}

export type Conversation = {
  id: string
  title: string
  lastMessage: string
  lastMessageTime: string
}
export type Source = {
  id: string
  url: string | null
  text: string
  name: string
  title?: string
  source_type?: string
  phase?: string | null
  status?: string | null
}

export type Message = {
  id: string | null
  content: string
  conversationId?: string
  role: 'user' | 'assistant'
  timestamp: string
  sources: Source[]
  urls?: string[]
}
