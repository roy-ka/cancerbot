import { test, expect } from '@playwright/test'

/**
 * Loading a conversation's messages must never overwrite what's on screen
 * with stale data. Both races are forced deterministically here by delaying
 * the /messages/ response:
 *  1. A reply that arrives before the conversation finishes loading must
 *     survive the load.
 *  2. A slow load for a conversation the user already left must not replace
 *     the conversation they switched to.
 */

function messagesResponse(id: string, title: string, answer: string) {
  return {
    conversation: { id, title, updatedAt: new Date().toISOString(), use_profile_context: true, shared: false },
    messages: [
      { id: `${id}-q`, role: 'user', content: `Question for ${title}`, created_at: new Date().toISOString(), sources: [], truncated: false },
      { id: `${id}-a`, role: 'assistant', content: answer, created_at: new Date().toISOString(), sources: [], truncated: false },
    ],
    next_before: null,
  }
}

test.describe('Conversation load race', () => {
  test('a reply that arrives before the conversation loads stays on screen', async ({ page }) => {
    await page.routeWebSocket(/\/add_message\/ws$/, (ws) => {
      ws.onMessage((raw) => {
        const payload = JSON.parse(raw as string)
        ws.send(
          JSON.stringify({
            type: 'final',
            messages: [
              { id: 'race-user-1', role: 'user', content: payload.content, created_at: new Date().toISOString(), sources: [] },
              { id: 'race-reply-1', role: 'assistant', content: 'RACE REPLY that must survive the load', created_at: new Date().toISOString(), sources: [] },
            ],
          }),
        )
      })
    })

    // Every conversation load takes 4s, so the mocked instant reply always
    // lands first — the ordering that used to wipe it out.
    await page.route(/\/conversations\/[^/]+\/messages\//, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 4_000))
      await route.continue()
    })

    // The app opens the most recent conversation once the list loads; send
    // only after that load has started, so the race is guaranteed.
    const loadStarted = page.waitForRequest(/\/conversations\/[^/]+\/messages\//, { timeout: 15_000 })
    await page.goto('/')
    await expect(page.locator('textarea[name="input"]')).toBeVisible({ timeout: 15_000 })
    await loadStarted

    await page.fill('textarea[name="input"]', 'Race question')
    await page.keyboard.press('Enter')
    await expect(page.locator('.message-bubble-assistant').last()).toContainText('RACE REPLY', { timeout: 3_000 })

    // Let the delayed load finish, then confirm it didn't replace the reply.
    await page.waitForResponse(/\/conversations\/[^/]+\/messages\//, { timeout: 10_000 })
    await page.waitForTimeout(500)
    await expect(page.locator('.message-bubble-assistant').last()).toContainText('RACE REPLY')
    await expect(page.locator('.message-bubble-user').last()).toContainText('Race question')
  })

  test('a slow load for a conversation you already left does not replace the current one', async ({ page }) => {
    // Fully mocked: two conversations in the sidebar, one whose messages take
    // 3s to load and one that loads instantly.
    const slowId = 'race-slow-conversation'
    const fastId = 'race-fast-conversation'
    const now = new Date().toISOString()
    await page.route(/\/conversations\/(\?.*)?$/, (route) =>
      route.fulfill({
        json: {
          conversations: [
            { id: slowId, title: 'Race slow', updatedAt: now, lastMessage: 'q', lastMessageTime: now },
            { id: fastId, title: 'Race fast', updatedAt: now, lastMessage: 'q', lastMessageTime: now },
          ],
        },
      }),
    )
    await page.route(new RegExp(`/conversations/${slowId}/messages/`), async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 3_000))
      await route.fulfill({ json: messagesResponse(slowId, 'Race slow', 'SLOW ANSWER from the conversation you left') })
    })
    await page.route(new RegExp(`/conversations/${fastId}/messages/`), (route) =>
      route.fulfill({ json: messagesResponse(fastId, 'Race fast', 'FAST ANSWER from the current conversation') }),
    )

    await page.goto('/')
    await expect(page.locator('textarea[name="input"]')).toBeVisible({ timeout: 15_000 })

    await page.locator('.conversation-item').filter({ hasText: 'Race slow' }).click()
    await page.locator('.conversation-item').filter({ hasText: 'Race fast' }).click()
    await expect(page.locator('.message-bubble-assistant').last()).toContainText('FAST ANSWER', { timeout: 5_000 })

    // Wait past the slow load's delay, then confirm it was ignored.
    await page.waitForTimeout(3_500)
    await expect(page.locator('.message-bubble-assistant').last()).toContainText('FAST ANSWER')
    await expect(page.getByText('SLOW ANSWER')).toHaveCount(0)
  })
})
