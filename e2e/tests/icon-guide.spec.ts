import { test, expect } from '@playwright/test'

/**
 * Chat-page icon tutorial. Deterministic — no LLM or search involved.
 *
 * The auto-open condition is "the user has no conversations yet", so the
 * conversations-list response is stubbed to drive both branches rather than
 * depending on whatever history the e2e account happens to have.
 */
test.describe('Icon guide', () => {
  const CONVERSATION_LIST = /\/conversations\/$/

  test('opens from the sidebar and lists the icons by area', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('textarea[name="input"]')).toBeVisible({ timeout: 15_000 })
    await page.waitForLoadState('networkidle')

    // Dismiss it first if the account happens to have no conversations
    const dismiss = page.getByTestId('icon-guide-dismiss')
    if (await dismiss.isVisible()) await dismiss.click()

    await page.getByTestId('icon-guide-trigger').click()

    await expect(page.getByTestId('icon-guide-title')).toBeVisible()
    const rows = page.getByTestId('icon-guide-row')
    expect(await rows.count()).toBeGreaterThanOrEqual(10)

    // A few representative briefs
    await expect(page.getByText('Find trials to join', { exact: true })).toBeVisible()
    await expect(page.getByText('Translate', { exact: true })).toBeVisible()
    await expect(page.getByText('Trial badge', { exact: true })).toBeVisible()

    // Never documents the ninja-only view
    await expect(page.getByText(/ninja/i)).toHaveCount(0)
  })

  test('dismissing closes it', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('textarea[name="input"]')).toBeVisible({ timeout: 15_000 })
    await page.waitForLoadState('networkidle')

    const dismiss = page.getByTestId('icon-guide-dismiss')
    if (await dismiss.isVisible()) await dismiss.click()

    await page.getByTestId('icon-guide-trigger').click()
    await expect(page.getByTestId('icon-guide-title')).toBeVisible()

    await page.getByTestId('icon-guide-dismiss').click()
    await expect(page.getByTestId('icon-guide-title')).toBeHidden()
  })

  test('opens on its own for a user with no conversations', async ({ page }) => {
    await page.route(CONVERSATION_LIST, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ conversations: [] }),
      }),
    )

    await page.goto('/')
    await expect(page.getByTestId('icon-guide-title')).toBeVisible({ timeout: 15_000 })
  })

  test('stays closed for a user who already has conversations', async ({ page }) => {
    await page.route(CONVERSATION_LIST, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          conversations: [
            {
              id: '00000000-0000-0000-0000-000000000001',
              title: 'Existing conversation',
              lastMessage: 'hello',
              lastMessageTime: 'now',
            },
          ],
        }),
      }),
    )

    await page.goto('/')
    await expect(page.locator('textarea[name="input"]')).toBeVisible({ timeout: 15_000 })
    await page.waitForLoadState('networkidle')

    // It must not flash open while the conversations request is in flight either
    await expect(page.getByTestId('icon-guide-title')).toHaveCount(0)
  })
})
