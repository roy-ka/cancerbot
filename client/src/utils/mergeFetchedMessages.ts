import type { Message } from '../types'

/** The message list to show once a conversation's messages have loaded.
 *
 * A question sent while that fetch was still in flight exists only as an
 * optimistic `temp-` message in `prev`; replacing the list with the fetched
 * one would hide it until the answer finished streaming (seconds with Groq,
 * much longer with a local model). So pending messages for this conversation
 * are kept after the fetched ones — unless the server already saved that
 * question, in which case it's the fetched list's last message.
 */
export function mergeFetchedMessages(
  prev: Message[],
  fetched: Message[],
  conversationId: string,
): Message[] {
  const last = fetched[fetched.length - 1]
  const pending = prev.filter(
    (m) =>
      m.id?.startsWith('temp-') &&
      m.conversationId === conversationId &&
      !(last?.role === 'user' && last.content === m.content),
  )
  return pending.length === 0 ? fetched : [...fetched, ...pending]
}
