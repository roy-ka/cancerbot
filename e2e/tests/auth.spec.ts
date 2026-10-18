import { test, expect } from '@playwright/test'
import { requestCodeViaUi, signInViaUi } from '../helpers'

const E2E_EMAIL = process.env.E2E_EMAIL ?? 'e2e-test@example.com'

const digits = (page: import('@playwright/test').Page) =>
  page.locator('[data-testid^="code-digit-"]').evaluateAll((els) => els.map((el) => (el as HTMLInputElement).value))

const wrongCode = (code: string) => (code === '000000' ? '111111' : '000000')

// Unauthenticated tests — clear the saved storageState for this describe block only
test.describe('unauthenticated', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('login page asks for an email only — no password', async ({ page }) => {
    await page.goto('/login')
    await expect(page.locator('input[name="email"]')).toBeVisible()
    await expect(page.locator('input[type="password"]')).toHaveCount(0)
    await expect(page.getByRole('button', { name: /forgot password/i })).toHaveCount(0)
  })

  test('wrong code shows an error and clears the boxes', async ({ page }) => {
    const code = await requestCodeViaUi(page, E2E_EMAIL)
    await page.keyboard.type(wrongCode(code))

    await expect(page.getByText(/incorrect code/i)).toBeVisible()
    await expect.poll(() => digits(page)).toEqual(['', '', '', '', '', ''])
    await expect(page.getByTestId('code-digit-0')).toBeFocused()
    await expect(page).toHaveURL(/\/login/)
  })

  test('correct code navigates into the app', async ({ page }) => {
    await signInViaUi(page, E2E_EMAIL)
    await expect(page).toHaveURL(/\/(terms|onboarding|chat)/, { timeout: 15_000 })
  })

  test('typing moves through the boxes and Backspace goes back', async ({ page }) => {
    await requestCodeViaUi(page, E2E_EMAIL)

    await page.keyboard.type('12')
    await expect(page.getByTestId('code-digit-2')).toBeFocused()
    await page.keyboard.press('Backspace')
    await expect(page.getByTestId('code-digit-1')).toBeFocused()
    await expect.poll(() => digits(page)).toEqual(['1', '', '', '', '', ''])
    await page.keyboard.press('Backspace')
    await expect(page.getByTestId('code-digit-0')).toBeFocused()
    await expect.poll(() => digits(page)).toEqual(['', '', '', '', '', ''])
  })

  test('pasting the code fills every box and signs in', async ({ page }) => {
    const code = await requestCodeViaUi(page, E2E_EMAIL)

    // Pasted text often carries spaces or a dash; only the digits count.
    const pasted = `${code.slice(0, 3)}-${code.slice(3)} `
    await page.getByTestId('code-digit-0').evaluate((el, text) => {
      const data = new DataTransfer()
      data.setData('text', text)
      el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }))
    }, pasted)

    await expect(page).toHaveURL(/\/(terms|onboarding|chat)/, { timeout: 15_000 })
  })

  test('"Use a different email" returns to the email step', async ({ page }) => {
    await requestCodeViaUi(page, E2E_EMAIL)
    await expect(page.getByText(/resend in \d+s/i)).toBeVisible()
    await page.getByRole('button', { name: /use a different email/i }).click()
    await expect(page.locator('input[name="email"]')).toHaveValue(E2E_EMAIL)
  })

  test('an unknown email still gets the code screen', async ({ page }) => {
    // The response must not reveal whether an account exists.
    await page.goto('/login')
    await page.fill('input[name="email"]', `nobody-${Date.now()}@example.com`)
    await page.click('button[type="submit"]')
    await expect(page.getByText(/check your email/i)).toBeVisible()
    await expect(page.getByTestId('dev-code')).toHaveCount(0)
  })

  test('registration takes a name and email, then a code', async ({ page }) => {
    await page.goto('/login')
    await page.getByRole('button', { name: /^register$/i }).click()

    await expect(page.locator('input[name="first_name"]')).toBeVisible()
    await expect(page.locator('input[name="last_name"]')).toBeVisible()
    await expect(page.locator('input[type="password"]')).toHaveCount(0)

    // A unique email per run so we don't collide with a prior registration
    const email = `e2e-reg-${Date.now()}@example.com`
    await page.fill('input[name="first_name"]', 'Grace')
    await page.fill('input[name="last_name"]', 'Hopper')
    await page.fill('input[name="email"]', email)
    await page.locator('input[type="checkbox"]').check()
    await page.click('button[type="submit"]')

    await expect(page.getByText(/check your email/i)).toBeVisible({ timeout: 15_000 })
    const code = (await page.getByTestId('dev-code').locator('strong').textContent())?.trim() ?? ''
    await page.keyboard.type(code)

    // A brand-new account always starts at the terms page
    await expect(page).toHaveURL(/terms/, { timeout: 15_000 })
  })

  test('registration needs the terms accepted', async ({ page }) => {
    await page.goto('/login')
    await page.getByRole('button', { name: /^register$/i }).click()
    await page.fill('input[name="first_name"]', 'Grace')
    await page.fill('input[name="last_name"]', 'Hopper')
    await page.fill('input[name="email"]', `e2e-reg-terms-${Date.now()}@example.com`)
    await expect(page.getByRole('button', { name: /create account/i })).toBeDisabled()
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
