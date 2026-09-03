import { test, expect } from '@playwright/test'

test.describe('Message options', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('textarea[name="input"]')).toBeVisible({ timeout: 15_000 })
  })

  test('thumbs up toggles feedback on an assistant message', async ({ page }) => {
    await page.fill('textarea[name="input"]', 'What is metastasis?')
    await page.keyboard.press('Enter')

    const assistantBubble = page.locator('.message-bubble-assistant').last()
    await expect(async () => {
      const text = await assistantBubble.textContent()
      expect(text?.trim().length).toBeGreaterThan(20)
    }).toPass({ timeout: 90_000 })

    const upvote = assistantBubble.getByRole('button', { name: 'Good answer' })
    await upvote.click()
    await expect(assistantBubble.getByRole('button', { name: 'Remove upvote' })).toBeVisible({ timeout: 10_000 })

    // Toggling the same vote again clears it
    await assistantBubble.getByRole('button', { name: 'Remove upvote' }).click()
    await expect(assistantBubble.getByRole('button', { name: 'Good answer' })).toBeVisible({ timeout: 10_000 })
  })

  test('split creates a new conversation with the copied answer', async ({ page }) => {
    await page.fill('textarea[name="input"]', 'What is angiogenesis in cancer?')
    await page.keyboard.press('Enter')

    const assistantBubble = page.locator('.message-bubble-assistant').last()
    await expect(async () => {
      const text = await assistantBubble.textContent()
      expect(text?.trim().length).toBeGreaterThan(20)
    }).toPass({ timeout: 90_000 })

    const answerText = (await assistantBubble.textContent())?.trim().slice(0, 30)

    await assistantBubble.getByRole('button', { name: 'Split into a new conversation from here' }).click()

    // The split conversation opens with the same question/answer copied in
    await expect(page.locator('.message-bubble-user').last()).toContainText('angiogenesis', { timeout: 10_000 })
    if (answerText) {
      await expect(page.locator('.message-bubble-assistant').last()).toContainText(answerText, { timeout: 10_000 })
    }
  })
})
