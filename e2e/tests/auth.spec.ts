import { test, expect, Browser } from '@playwright/test'

const E2E_EMAIL = process.env.E2E_EMAIL ?? 'e2e-test@example.com'
const E2E_PASSWORD = process.env.E2E_PASSWORD ?? 'E2eTest123!'

// Unauthenticated tests — clear the saved storageState for this describe block only
test.describe('unauthenticated', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('login with wrong password shows error', async ({ browser }: { browser: Browser }) => {
    const ctx = await browser.newContext()
    const page = await ctx.newPage()
    await page.goto('/login')

    await page.fill('input[name="email"]', E2E_EMAIL)
    await page.fill('input[name="password"]', 'wrong-password-123')
    await page.click('button[type="submit"]')

    await expect(page.getByText(/invalid|incorrect|wrong|failed/i)).toBeVisible()
    await ctx.close()
  })

  test('login with correct credentials navigates to chat', async ({ browser }: { browser: Browser }) => {
    const ctx = await browser.newContext()
    const page = await ctx.newPage()
    await page.goto('/login')

    await page.fill('input[name="email"]', E2E_EMAIL)
    await page.fill('input[name="password"]', E2E_PASSWORD)
    await page.click('button[type="submit"]')

    // After login the app redirects to / or /terms (first login) — both are valid
    await expect(page).toHaveURL(/\/(terms|chat)?(\?.*)?$/, { timeout: 15_000 })
    await ctx.close()
  })

  test('registration form has separate first and last name fields', async ({ browser }: { browser: Browser }) => {
    const ctx = await browser.newContext()
    const page = await ctx.newPage()
    await page.goto('/login')

    // Switch to the Register tab
    await page.getByRole('button', { name: /^register$/i }).click()

    // The name field is now split in two
    await expect(page.locator('input[name="first_name"]')).toBeVisible()
    await expect(page.locator('input[name="last_name"]')).toBeVisible()
    await expect(page.locator('input[name="name"]')).toHaveCount(0)

    // A unique email per run so we don't collide with a prior registration
    const email = `e2e-reg-${Date.now()}@example.com`
    await page.fill('input[name="first_name"]', 'Grace')
    await page.fill('input[name="last_name"]', 'Hopper')
    await page.fill('input[name="email"]', email)
    await page.fill('input[name="password"]', 'SecurePass123!')
    await page.locator('input[type="checkbox"]').check()
    await page.click('button[type="submit"]')

    // Successful registration shows the "check your email" screen
    await expect(page.getByText(/check your email/i)).toBeVisible({ timeout: 15_000 })
    await ctx.close()
  })
})

// Authenticated test — uses the saved storageState from globalSetup
test('logout redirects to login page', async ({ page }) => {
  await page.goto('/')
  await expect(page).not.toHaveURL('/login')

  // Open account menu (PersonOutlineIcon button)
  await page.locator('button:has(svg[data-testid="PersonOutlineIcon"])').first().click()

  // Click logout item in the popup menu → opens confirmation dialog
  await page.getByRole('menuitem', { name: /logout/i }).click()

  // Confirm logout in the dialog
  await page.getByRole('button', { name: /yes.*log.*out/i }).click()

  await expect(page).toHaveURL(/login/, { timeout: 10_000 })
})
