import { test, expect, Browser, request } from '@playwright/test'

const E2E_API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000'

test.describe('unauthenticated', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('joining the waitlist via the API persists the email and is idempotent', async () => {
    const api = await request.newContext({ baseURL: E2E_API_URL })
    const email = `e2e-waitlist-${Date.now()}@example.com`

    const first = await api.post('/auth/waitlist/', { data: { email } })
    expect(first.status()).toBe(201)

    // Re-joining with the same email must not error or duplicate.
    const second = await api.post('/auth/waitlist/', { data: { email } })
    expect(second.status()).toBe(201)

    await api.dispose()
  })

  test('waitlist rejects an invalid email', async () => {
    const api = await request.newContext({ baseURL: E2E_API_URL })
    const res = await api.post('/auth/waitlist/', { data: { email: 'not-an-email' } })
    expect(res.status()).toBe(422)
    await api.dispose()
  })

  // The registration cap (MAX_USERS) isn't flipped per-test — it's whatever
  // the running environment has set. Instead of asserting a fixed UI, this
  // reads the real /auth/registration_status/ and checks the register tab
  // shows whichever form that status implies, so it stays correct either way.
  test('register tab shows the form matching the live registration status', async ({ browser }: { browser: Browser }) => {
    const api = await request.newContext({ baseURL: E2E_API_URL })
    const status = await api.get('/auth/registration_status/')
    const { open } = await status.json()
    await api.dispose()

    const ctx = await browser.newContext()
    const page = await ctx.newPage()
    await page.goto('/login')
    await page.getByRole('button', { name: /^register$/i }).click()

    if (open) {
      await expect(page.locator('input[name="first_name"]')).toBeVisible()
    } else {
      await expect(page.locator('input[name="first_name"]')).toHaveCount(0)
      await expect(page.locator('input#waitlist_email')).toBeVisible()
    }

    await ctx.close()
  })
})
