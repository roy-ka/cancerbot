import { test, expect, request as playwrightRequest } from '@playwright/test'
import { registerUser, signInViaUi } from '../helpers'

const E2E_API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000'

test.describe('Health profile onboarding', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('register -> terms -> onboarding -> chat, then edit and clear from the account menu', async ({ page }) => {
    const email = `onboarding-e2e-${Date.now()}@example.com`

    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    await registerUser(api, { first_name: 'Onboarding', last_name: 'E2E', email })
    await api.dispose()

    await signInViaUi(page, email)
    await page.waitForLoadState('networkidle', { timeout: 15_000 })

    // First-time login always lands on /terms
    await expect(page).toHaveURL(/terms/, { timeout: 10_000 })
    await page.locator('input[type="checkbox"]').check()
    await page.getByRole('button', { name: /accept and continue/i }).click()

    // Terms acceptance now lands on /onboarding, not /chat directly
    await expect(page).toHaveURL(/onboarding/, { timeout: 10_000 })
    await expect(page.getByRole('button', { name: /^skip for now$/i })).toBeVisible()

    await page.fill('input[placeholder="e.g. Glioblastoma"]', 'Glioblastoma')
    await page.fill('input[placeholder="e.g. IV"]', 'IV')
    await page.getByRole('button', { name: /^save$/i }).click()

    // Saving takes us to chat, and the per-conversation toggle appears
    // because this account now has a populated profile.
    await expect(page).toHaveURL(/chat/, { timeout: 10_000 })

    // A brand-new account with zero conversations auto-opens the "Getting
    // around CancerBot" icon guide, which otherwise steals focus from the
    // composer (a keyboard Enter would submit into the dialog, not send the
    // message) — wait for and dismiss it before typing anything.
    const guideDismiss = page.getByRole('button', { name: /^got it$/i })
    await expect(guideDismiss).toBeVisible({ timeout: 10_000 })
    await guideDismiss.click()
    await expect(guideDismiss).not.toBeVisible()

    await page.fill('textarea[name="input"]', 'What is glioblastoma?')
    await page.getByRole('button', { name: /^send$/i }).click()

    await expect(page.getByText(/using your health profile/i)).toBeVisible({ timeout: 15_000 })

    // Re-open from the account menu — should be pre-filled and offer Clear
    // instead of Skip.
    await page.locator('button:has(svg[data-testid="PersonOutlineIcon"])').first().click()
    await page.getByRole('menuitem', { name: /health profile/i }).click()
    await expect(page).toHaveURL(/onboarding/, { timeout: 10_000 })
    await expect(page.locator('input[placeholder="e.g. Glioblastoma"]')).toHaveValue('Glioblastoma')
    await expect(page.getByRole('button', { name: /^skip for now$/i })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /clear profile/i })).toBeVisible()

    await page.getByRole('button', { name: /clear profile/i }).click()
    await expect(page.getByRole('button', { name: /^skip for now$/i })).toBeVisible({ timeout: 10_000 })
  })

  test('skipping onboarding lands on chat without the profile toggle', async ({ page }) => {
    const email = `onboarding-skip-e2e-${Date.now()}@example.com`

    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    await registerUser(api, { first_name: 'Onboarding', last_name: 'Skip', email })
    await api.dispose()

    await signInViaUi(page, email)
    await page.waitForLoadState('networkidle', { timeout: 15_000 })

    await expect(page).toHaveURL(/terms/, { timeout: 10_000 })
    await page.locator('input[type="checkbox"]').check()
    await page.getByRole('button', { name: /accept and continue/i }).click()

    await expect(page).toHaveURL(/onboarding/, { timeout: 10_000 })
    await page.getByRole('button', { name: /^skip for now$/i }).click()
    await expect(page).toHaveURL(/chat/, { timeout: 10_000 })

    // No populated profile — the toggle never renders, on any conversation.
    await page.fill('textarea[name="input"]', 'What is glioblastoma?')
    await page.keyboard.press('Enter')
    await expect(page.getByText(/using your health profile/i)).toHaveCount(0)

    // A second protected-page visit must not be sent back to /onboarding —
    // the empty row from Skip is what prevents that.
    await page.goto('/chat')
    await page.waitForLoadState('networkidle', { timeout: 10_000 })
    await expect(page).toHaveURL(/chat/)
  })
})
