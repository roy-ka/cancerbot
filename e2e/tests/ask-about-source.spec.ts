import { test, expect } from '@playwright/test'

/**
 * Clicking a citation opens the source popover; "Ask about this source" puts
 * that source's id in the message box (the backend fetches the source by id
 * and answers from it). The conversation is mocked so the citation is
 * deterministic.
 */
test.describe('Ask about a source', () => {
  test('the source popover puts the source id in the message box, once', async ({ page }) => {
    const now = new Date().toISOString()
    await page.route(/\/conversations\/(\?.*)?$/, (route) =>
      route.fulfill({
        json: { conversations: [{ id: 'ask-conv', title: 'Ask about source', updatedAt: now, lastMessage: 'q', lastMessageTime: now }] },
      }),
    )
    await page.route(/\/conversations\/ask-conv\/messages\//, (route) =>
      route.fulfill({
        json: {
          conversation: { id: 'ask-conv', title: 'Ask about source', updatedAt: now, use_profile_context: true, shared: false },
          messages: [
            { id: 'ask-q', role: 'user', content: 'What is the Warburg effect?', created_at: now, sources: [] },
            {
              id: 'ask-a',
              role: 'assistant',
              content: 'Cancer cells favour glycolysis [pmid:12345].',
              created_at: now,
              sources: [{ id: 'pmid:12345', url: null, name: 'Warburg Paper', text: 'Abstract of the Warburg paper.' }],
            },
          ],
          next_before: null,
        },
      }),
    )

    await page.goto('/')
    await expect(page.locator('.message-bubble-assistant').last()).toContainText('Cancer cells favour glycolysis', { timeout: 15_000 })

    const input = page.locator('textarea[name="input"]')
    for (let i = 0; i < 2; i++) {
      await page.locator('.message-bubble-assistant').last().getByText('Warburg Paper').click()
      await expect(page.getByText('Abstract of the Warburg paper.')).toBeVisible()
      await page.getByRole('button', { name: 'Ask about this source' }).click()
    }

    await expect(input).toHaveValue('[pmid:12345] ')
    await expect(input).toBeFocused()
  })

  test('shared, read-only conversations have no ask button', async ({ page }) => {
    const now = new Date().toISOString()
    await page.route(/\/shared\/ask-share-token$/, (route) =>
      route.fulfill({
        json: {
          conversation: { title: 'Shared' },
          messages: [
            {
              id: 'share-a',
              role: 'assistant',
              content: 'Cancer cells favour glycolysis [pmid:12345].',
              created_at: now,
              sources: [{ id: 'pmid:12345', url: null, name: 'Warburg Paper', text: 'Abstract of the Warburg paper.' }],
            },
          ],
        },
      }),
    )
    await page.goto('/s/ask-share-token')
    await page.getByText('Warburg Paper').click()
    await expect(page.getByText('Abstract of the Warburg paper.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Ask about this source' })).toHaveCount(0)
  })

  test('your question keeps its source id; an invented citation in an answer stays hidden', async ({ page }) => {
    const now = new Date().toISOString()
    await page.route(/\/conversations\/(\?.*)?$/, (route) =>
      route.fulfill({
        json: { conversations: [{ id: 'ask-shown', title: 'Ask shown', updatedAt: now, lastMessage: 'q', lastMessageTime: now }] },
      }),
    )
    await page.route(/\/conversations\/ask-shown\/messages\//, (route) =>
      route.fulfill({
        json: {
          conversation: { id: 'ask-shown', title: 'Ask shown', updatedAt: now, use_profile_context: true, shared: false },
          messages: [
            { id: 'shown-q', role: 'user', content: '[pmid:12345] what about [the second trial]?', created_at: now, sources: [] },
            { id: 'shown-a', role: 'assistant', content: 'It enrolled 40 patients [pmid:99999].', created_at: now, sources: [] },
          ],
          next_before: null,
        },
      }),
    )

    await page.goto('/')
    await expect(page.locator('.message-bubble-user').last()).toHaveText('[pmid:12345] what about [the second trial]?', { timeout: 15_000 })
    await expect(page.locator('.message-bubble-assistant').last()).toContainText('It enrolled 40 patients')
    await expect(page.locator('.message-bubble-assistant').last()).not.toContainText('pmid:99999')
  })
})
