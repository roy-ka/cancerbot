import { test, expect } from '@playwright/test'

test.describe('Share conversation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('textarea[name="input"]')).toBeVisible({ timeout: 15_000 })

    await page.fill('textarea[name="input"]', 'What is metastasis?')
    await page.keyboard.press('Enter')
    const assistantBubble = page.locator('.message-bubble-assistant').last()
    await expect(async () => {
      const text = await assistantBubble.textContent()
      expect(text?.trim().length).toBeGreaterThan(20)
    }).toPass({ timeout: 90_000 })
  })

  test('a shared link is viewable, unauthenticated, then stops working after revoke', async ({ page, browser }) => {
    await page.getByRole('button', { name: 'Share conversation' }).click()

    const shareInput = page.locator('input[readonly]')
    await expect(shareInput).toBeVisible({ timeout: 15_000 })
    const shareUrl = await shareInput.inputValue()
    expect(shareUrl).toMatch(/\/s\/[\w-]+$/)

    // Fresh, unauthenticated context — a real "someone else opened the link" check.
    // browser.newContext() alone inherits this config's default storageState (the
    // logged-in e2e account), so the empty state must be passed explicitly here.
    const anonContext = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    const anonPage = await anonContext.newPage()
    await anonPage.goto(shareUrl)

    // Two matches expected: the page heading (conversation title) and the
    // user's message bubble happen to be the same short text here.
    await expect(anonPage.getByText('What is metastasis?').last()).toBeVisible({ timeout: 15_000 })
    // Read-only: no vote/split controls (those require an authenticated conversationId)
    await expect(anonPage.getByRole('button', { name: 'Good answer' })).toHaveCount(0)
    await expect(anonPage.getByRole('button', { name: /split into a new conversation/i })).toHaveCount(0)

    // Revoke from the owning session
    await page.getByRole('button', { name: 'Stop sharing' }).click()
    await expect(page.getByRole('button', { name: 'Stop sharing' })).toHaveCount(0)

    await anonPage.reload()
    await expect(anonPage.getByText(/invalid or has been revoked/i)).toBeVisible({ timeout: 15_000 })

    await anonContext.close()
  })
})
