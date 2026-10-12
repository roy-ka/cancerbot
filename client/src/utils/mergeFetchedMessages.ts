import type { Message } from '../types'

/** The message list to show once a conversation's messages have loaded.
 *
 * `before` is the list that was on screen when the load started. Anything
 * added since — a question sent while it was in flight, or the reply that
 * already came back for it — would be wiped out by simply replacing the list
 * with the fetched one, so those are kept after the fetched history. They're
 * dropped when the fetched list already has them: same id, or (for a
 * still-unsaved `temp-` question) the server already saved that question as
 * its last message.
 */
export function mergeFetchedMessages(
  prev: Message[],
  fetched: Message[],
  before: Message[],
): Message[] {
  const fetchedIds = new Set(fetched.map((m) => m.id).filter(Boolean))
  const last = fetched[fetched.length - 1]
  const added = prev.filter(
    (m) =>
      !before.includes(m) &&
      !(m.id && fetchedIds.has(m.id)) &&
      !(m.id?.startsWith('temp-') && last?.role === 'user' && last.content === m.content),
  )
  return added.length === 0 ? fetched : [...fetched, ...added]
}
