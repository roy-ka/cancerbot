import { test, expect } from '@playwright/test'

test.describe('Chat', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    // Wait for the app to load (input field visible)
    await expect(page.locator('textarea[name="input"]')).toBeVisible({ timeout: 15_000 })
  })

  test('sends a message and receives a streamed assistant response', async ({ page }) => {
    const question = 'What is lung cancer?'

    // Type and submit the question
    await page.fill('textarea[name="input"]', question)
    await page.keyboard.press('Enter')

    // User message bubble should appear immediately
    await expect(page.locator('.message-bubble-user').last()).toContainText(question, { timeout: 10_000 })

    // Wait until the assistant bubble has meaningful text. Use polling because:
    // 1. The empty streaming bubble appears immediately (before tokens arrive)
    // 2. Normal English sentences have no 20-char non-whitespace runs
    const assistantBubble = page.locator('.message-bubble-assistant').last()
    await expect(async () => {
      const text = await assistantBubble.textContent()
      expect(text?.trim().length).toBeGreaterThan(20)
    }).toPass({ timeout: 90_000 })
  })

  test('assistant response contains citation chips', async ({ page }) => {
    await page.fill('textarea[name="input"]', 'What treatments exist for glioblastoma?')
    await page.keyboard.press('Enter')

    const assistantBubble = page.locator('.message-bubble-assistant').last()

    // Wait for streaming to complete — poll until the bubble has substantial text
    await expect(async () => {
      const text = await assistantBubble.textContent()
      expect(text?.trim().length).toBeGreaterThan(50)
    }).toPass({ timeout: 90_000 })

    // Citation chips are inline spans rendered from resolved source IDs.
    // The chip text is the source identifier: pmid:xxx, doi:xxx, or "wiki: Title".
    // These are synchronously set when the WebSocket final message arrives.
    await expect(async () => {
      const text = await assistantBubble.textContent() ?? ''
      expect(/pmid:|doi:|wiki:/i.test(text)).toBe(true)
    }).toPass({ timeout: 15_000 })
  })

  test('can send multiple messages in sequence', async ({ page }) => {
    await page.fill('textarea[name="input"]', 'What is chemotherapy?')
    await page.keyboard.press('Enter')

    const first = page.locator('.message-bubble-assistant').first()
    await expect(first).toBeVisible({ timeout: 90_000 })

    // After first reply, input should be re-enabled
    await expect(page.locator('textarea[name="input"]')).toBeEnabled({ timeout: 10_000 })

    await page.fill('textarea[name="input"]', 'What are its side effects?')
    await page.keyboard.press('Enter')

    const second = page.locator('.message-bubble-assistant').nth(1)
    await expect(second).toBeVisible({ timeout: 90_000 })
  })
})
