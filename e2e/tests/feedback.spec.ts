import { test, expect } from '@playwright/test'

test.describe('Bug report / feedback dialog', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('textarea[name="input"]')).toBeVisible({ timeout: 15_000 })
  })

  test('submits a feedback report via the type toggle', async ({ page }) => {
    await page.getByRole('button', { name: /report a bug or send feedback/i }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Report a Bug')).toBeVisible()

    await dialog.getByRole('button', { name: /^feedback$/i }).click()
    await expect(dialog.getByText('Send Feedback')).toBeVisible()
    // "How to reproduce" only applies to bugs
    await expect(dialog.getByLabel('How to reproduce')).toHaveCount(0)

    await dialog.getByLabel('Title').fill('Really like the new reranker')
    await dialog.getByLabel('Your feedback').fill('Answers feel a lot more relevant now.')
    await dialog.getByRole('button', { name: /^submit$/i }).click()

    await expect(dialog.getByText(/thank you.*feedback was submitted/i)).toBeVisible({ timeout: 10_000 })
  })

  test('submits a bug report with the default type', async ({ page }) => {
    await page.getByRole('button', { name: /report a bug or send feedback/i }).click()

    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Title').fill('Chat scrolls to the wrong place')
    await dialog.getByLabel('Description').fill('After sending a message the view jumps up.')
    await dialog.getByLabel('How to reproduce').fill('Send a message, watch the scroll position.')
    await dialog.getByRole('button', { name: /^submit$/i }).click()

    await expect(dialog.getByText(/thank you.*report was submitted/i)).toBeVisible({ timeout: 10_000 })
  })
})
