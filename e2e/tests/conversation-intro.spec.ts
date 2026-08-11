import { test, expect } from '@playwright/test'

/**
 * The new-conversation intro explainer, rendered as an assistant message.
 * Deterministic (no LLM/search needed): it renders purely from client state
 * whenever the selected conversation has no messages.
 */
test.describe('New-conversation intro', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('textarea[name="input"]')).toBeVisible({ timeout: 15_000 })
    // The e2e user may already have conversations, so on load the app fetches
    // them and (once) auto-selects a non-empty one. Wait for those fetches to
    // settle first — otherwise that auto-select can fire *after* our click and
    // clear the intro again, making the intro only transiently visible.
    await page.waitForLoadState('networkidle')
    // Now the one-time auto-select has run, so selecting "New Conversation"
    // sticks. Retry the click defensively in case the list is still settling.
    await expect(async () => {
      await page.getByText('New Conversation').first().click()
      await expect(page.getByTestId('conversation-intro')).toBeVisible({ timeout: 2_000 })
    }).toPass({ timeout: 20_000 })
  })

  test('shows the constant RAG intro message as an assistant bubble', async ({ page }) => {
    const intro = page.getByTestId('conversation-intro')
    await expect(intro).toContainText('This is a')
    await expect(intro).toContainText('To get the best answers, add context, keywords and such')
    // Styled as an assistant message so it reads as CancerBot's opening turn
    await expect(intro).toHaveClass(/message-bubble-assistant/)
    await expect(page.getByTestId('rag-link')).toBeVisible()
  })

  test('hovering the RAG link explains retrieval-augmented generation', async ({ page }) => {
    await page.getByTestId('rag-link').hover()
    await expect(page.getByRole('tooltip')).toContainText(/Retrieval-Augmented Generation/i)
  })

  test('surfaces 4–5 example prompts and clicking one fills the composer', async ({ page }) => {
    const tips = page.getByTestId('intro-tip')
    const count = await tips.count()
    expect(count).toBeGreaterThanOrEqual(4)
    expect(count).toBeLessThanOrEqual(5)

    const firstTip = tips.first()
    const tipText = (await firstTip.innerText()).trim()
    await firstTip.click()

    await expect(page.locator('textarea[name="input"]')).toHaveValue(tipText)
  })

  test('disappears on the first user message and is never persisted', async ({ page }) => {
    await page.fill('textarea[name="input"]', 'What is chemotherapy?')
    await page.keyboard.press('Enter')

    // The optimistic user message alone removes it — no need to wait for the LLM
    await expect(page.getByTestId('conversation-intro')).toBeHidden({ timeout: 10_000 })

    // And it is client-only: it never becomes part of the stored thread, so it
    // is still absent once the conversation is re-opened from the backend.
    await expect(page.locator('.message-bubble-user').last()).toContainText(
      'What is chemotherapy?',
      { timeout: 10_000 },
    )
    await page.reload()
    await expect(page.locator('textarea[name="input"]')).toBeVisible({ timeout: 15_000 })
    await page.waitForLoadState('networkidle')
    await expect(page.getByTestId('conversation-intro')).toHaveCount(0)
  })
})
