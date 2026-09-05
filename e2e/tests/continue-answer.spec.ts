import { test, expect } from '@playwright/test'

/**
 * A truncated (GROQ_MAX_TOKENS-cut) answer offers a "Continue" action that
 * extends it in place. Real LLM output isn't reliably truncatable on demand,
 * so the WebSocket is fully mocked here (page.routeWebSocket) — this still
 * exercises the actual frontend code path (Chat.tsx's handleContinue,
 * MessageItem's truncated banner/button, live-appended streaming text)
 * against a deterministic server response, rather than hoping a real answer
 * happens to run long. /conversations/create/ is a lightweight DB-only REST
 * call and is left to hit the real backend.
 *
 * page.routeWebSocket must be registered before the navigation that will
 * open the socket — it hooks the page's WebSocket constructor at
 * navigation time, so registering it after page.goto (as the other specs'
 * shared beforeEach does) silently never intercepts anything.
 */
test.describe('Truncated answer / Continue', () => {
  test('a truncated answer shows Continue, and continuing appends more text', async ({ page }) => {
    await page.routeWebSocket(/\/add_message\/ws$/, (ws) => {
      ws.onMessage((raw) => {
        const payload = JSON.parse(raw as string)

        if (payload.continue_message_id) {
          ws.send(JSON.stringify({ type: 'stage', stage: 'generating_answer', data: {} }))
          ws.send(JSON.stringify({ type: 'token', token: ' — more detail here.' }))
          ws.send(
            JSON.stringify({
              type: 'final',
              continued_message: {
                id: 'mock-msg-1',
                role: 'assistant',
                content: 'Cancer is a disease of uncontrolled cell growth — more detail here.',
                created_at: new Date().toISOString(),
                sources: [],
                truncated: false,
              },
            }),
          )
          return
        }

        ws.send(JSON.stringify({ type: 'stage', stage: 'generating_answer', data: {} }))
        ws.send(JSON.stringify({ type: 'token', token: 'Cancer is a disease of uncontrolled cell growth' }))
        ws.send(
          JSON.stringify({
            type: 'final',
            messages: [
              {
                id: 'mock-user-1',
                role: 'user',
                content: payload.content,
                created_at: new Date().toISOString(),
                sources: [],
              },
              {
                id: 'mock-msg-1',
                role: 'assistant',
                content: 'Cancer is a disease of uncontrolled cell growth',
                created_at: new Date().toISOString(),
                sources: [],
                truncated: true,
              },
            ],
            conversation: {
              id: 'mock-conv-1',
              title: 'Mock conversation',
              updatedAt: new Date().toISOString(),
              lastMessage: payload.content,
              lastMessageTime: 'now',
            },
          }),
        )
      })
    })

    await page.goto('/')
    await expect(page.locator('textarea[name="input"]')).toBeVisible({ timeout: 15_000 })

    await page.fill('textarea[name="input"]', 'What is cancer?')
    await page.keyboard.press('Enter')

    const assistantBubble = page.locator('.message-bubble-assistant').last()
    await expect(assistantBubble).toContainText('Cancer is a disease of uncontrolled cell growth', {
      timeout: 15_000,
    })
    await expect(assistantBubble.getByText('Response was cut short.')).toBeVisible()

    const continueButton = assistantBubble.getByRole('button', { name: 'Continue' })
    await expect(continueButton).toBeVisible()
    await continueButton.click()

    // The mock resolves the whole round trip near-instantly, so the
    // "Continuing..." interim state isn't reliably observable here — what
    // matters is the end state: appended text, truncated flag cleared.
    await expect(assistantBubble).toContainText('more detail here.', { timeout: 10_000 })
    await expect(assistantBubble.getByText('Response was cut short.')).not.toBeVisible()
    await expect(continueButton).not.toBeVisible()
  })
})
