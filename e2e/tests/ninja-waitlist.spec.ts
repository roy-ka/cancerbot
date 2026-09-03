import { test, expect, request } from '@playwright/test'

const E2E_API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000'
const NINJA_EMAIL = process.env.E2E_NINJA_EMAIL
const NINJA_PASSWORD = process.env.E2E_NINJA_PASSWORD

// Ninja credentials aren't a shared E2E fixture like E2E_EMAIL/E2E_PASSWORD —
// they're the real admin account, so no default is baked in here. Skip
// rather than fail when the environment hasn't provided them.
function ninjaConfigured() {
  return Boolean(NINJA_EMAIL && NINJA_PASSWORD)
}

test.describe('ninja waitlist', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('ninja can view the waitlist and send an invite', async ({ browser }) => {
    test.skip(!ninjaConfigured(), 'E2E_NINJA_EMAIL/E2E_NINJA_PASSWORD not set')

    const api = await request.newContext({ baseURL: E2E_API_URL })
    const email = `ninja-e2e-${Date.now()}@example.com`
    const joined = await api.post('/auth/waitlist/', { data: { email, name: 'Ninja E2E' } })
    expect(joined.status()).toBe(201)
    await api.dispose()

    const ctx = await browser.newContext()
    const page = await ctx.newPage()
    await page.goto('/login')
    await page.fill('input[name="email"]', NINJA_EMAIL!)
    await page.fill('input[name="password"]', NINJA_PASSWORD!)
    await page.click('button[type="submit"]')
    // Ninja login navigates straight to /ninja — it can no longer use
    // /chat as a regular user (see LoginForm.tsx's is_ninja branch).
    await expect(page).toHaveURL(/\/ninja(\?.*)?$/, { timeout: 15_000 })

    await page.getByRole('button', { name: /^waitlist$/i }).click()

    const row = page.getByTestId(`waitlist-row-${email}`)
    await expect(row).toBeVisible({ timeout: 10_000 })

    await row.getByRole('button', { name: /^invite$/i }).click()
    await expect(row.getByRole('button', { name: /resend invite/i })).toBeVisible({ timeout: 10_000 })

    await ctx.close()
  })

  test('invite link pre-fills and locks the registration email', async ({ browser }) => {
    test.skip(!ninjaConfigured(), 'E2E_NINJA_EMAIL/E2E_NINJA_PASSWORD not set')

    // Log in as ninja and invite a fresh waitlist entry via the API,
    // capturing the dev-mode invite_token from the response (no inbox to
    // read the real emailed link from in CI).
    const ninjaCtx = await request.newContext({ baseURL: E2E_API_URL })
    const login = await ninjaCtx.post('/auth/login/', { data: { email: NINJA_EMAIL, password: NINJA_PASSWORD } })
    expect(login.ok()).toBeTruthy()

    const email = `ninja-e2e-prefill-${Date.now()}@example.com`
    const joined = await ninjaCtx.post('/auth/waitlist/', { data: { email, name: 'Prefill E2E' } })
    expect(joined.status()).toBe(201)

    const list = await ninjaCtx.get('/ninja/waitlist/')
    const entry = (await list.json()).entries.find((e: { email: string }) => e.email === email)
    expect(entry).toBeTruthy()

    const invite = await ninjaCtx.post(`/ninja/waitlist/${entry.id}/invite`)
    const { invite_token: inviteToken } = await invite.json()
    expect(inviteToken).toBeTruthy()
    await ninjaCtx.dispose()

    // Follow the invite link as a fresh, unauthenticated visitor.
    const ctx = await browser.newContext()
    const page = await ctx.newPage()
    await page.goto(`/login?invite_token=${inviteToken}`)

    const emailField = page.locator('input[name="email"]')
    await expect(emailField).toHaveValue(email, { timeout: 10_000 })
    await expect(emailField).toBeDisabled()

    await ctx.close()
  })
})
