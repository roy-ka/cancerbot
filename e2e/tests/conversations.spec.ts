import { test, expect } from '@playwright/test'

test.describe('Conversations', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('textarea[name="input"]')).toBeVisible({ timeout: 15_000 })
  })

  test('sending a message creates a new conversation in the sidebar', async ({ page }) => {
    // Explicitly navigate to "new conversation" mode so the message doesn't go
    // into an existing conversation that was auto-selected on page load.
    await page.locator('.conversation-item').filter({ hasText: 'New Conversation' }).click()

    const initialCount = await page.locator('.conversation-item').count()

    await page.fill('textarea[name="input"]', 'Tell me about leukemia')
    await page.keyboard.press('Enter')

    // Wait for the assistant reply to confirm the conversation was saved
    await expect(page.locator('.message-bubble-assistant').last()).toBeVisible({ timeout: 90_000 })

    // Sidebar should now have one more conversation
    await expect(page.locator('.conversation-item')).toHaveCount(initialCount + 1, { timeout: 10_000 })
  })

  test('can select a previous conversation', async ({ page }) => {
    // Ensure at least one conversation exists; send one if the list is empty
    const count = await page.locator('.conversation-item').count()
    if (count === 0) {
      await page.fill('textarea[name="input"]', 'What is melanoma?')
      await page.keyboard.press('Enter')
      await expect(page.locator('.message-bubble-assistant').last()).toBeVisible({ timeout: 90_000 })
    }

    // Click the first real (non-"New Conversation") conversation
    const item = page.locator('.conversation-item').filter({ hasNotText: 'New Conversation' }).first()
    await item.click()

    // Chat area should show messages (at least the user message)
    await expect(page.locator('.message-bubble-user, .message-bubble-assistant').first()).toBeVisible({ timeout: 10_000 })
  })

  test('delete icon appears on hover and conversation is removed after confirmation', async ({ page }) => {
    // Create a conversation to delete
    await page.fill('textarea[name="input"]', 'What is pancreatic cancer?')
    await page.keyboard.press('Enter')
    await expect(page.locator('.message-bubble-assistant').last()).toBeVisible({ timeout: 90_000 })

    // Find the newly created conversation (last item in sidebar)
    const item = page.locator('.conversation-item').last()
    const title = await item.locator('.conversation-item-title').textContent()
    const countBefore = await page.locator('.conversation-item').count()

    // Hover to reveal the delete button
    await item.hover()
    const deleteBtn = item.locator('.conversation-item-delete-btn')
    await expect(deleteBtn).toBeVisible({ timeout: 5_000 })

    // Click the delete button
    await deleteBtn.click()

    // Confirmation dialog should appear with the conversation title
    await expect(page.getByRole('dialog')).toBeVisible()
    if (title) {
      await expect(page.getByRole('dialog')).toContainText(title)
    }

    // Confirm deletion
    await page.getByRole('button', { name: /^delete$/i }).click()

    // Dialog closes and the sidebar has one fewer conversation
    // (Don't check item visibility — the locator re-evaluates dynamically and
    //  would resolve to the new last item which is still visible.)
    await expect(page.getByRole('dialog')).not.toBeVisible({ timeout: 5_000 })
    await expect(page.locator('.conversation-item')).toHaveCount(countBefore - 1, { timeout: 5_000 })
  })
})
