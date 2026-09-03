/**
 * Account deletion flow: request → confirm (schedules a 7-day grace period) →
 * login blocked with a cancel option → cancel restores normal access.
 *
 * Uses a dedicated throwaway account (not the shared E2E_EMAIL) — this flow
 * schedules deletion and blocks login, which would break every other spec
 * that relies on the shared account's persisted storageState.
 */
import { test, expect, request as playwrightRequest } from '@playwright/test'

const E2E_API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000'

// Fresh browser session — do not reuse the shared E2E_EMAIL storageState.
test.use({ storageState: { cookies: [], origins: [] } })

// Each test here registers its own throwaway account, so it needs
// registration open — skip rather than fail when MAX_USERS has capped
// signups (see waitlist.spec.ts for the gated-registration coverage).
async function registrationIsOpen(): Promise<boolean> {
  const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
  const res = await api.get('/auth/registration_status/')
  const { open } = await res.json()
  await api.dispose()
  return open
}

test.describe('Account deletion', () => {
  test('request, confirm, grace-period login block, and cancel', async ({ page }) => {
    test.skip(!(await registrationIsOpen()), 'registration is closed (MAX_USERS reached)')
    const email = `delete-e2e-${Date.now()}@example.com`
    const password = 'DeleteE2e123!'

    // Register + verify via direct API call (mirrors global-setup.ts)
    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    const reg = await api.post('/auth/register/', {
      data: { first_name: 'Delete', last_name: 'E2E', email, password },
    })
    expect(reg.status()).toBe(201)
    const { verification_token: verificationToken } = await reg.json()
    const verify = await api.get(`/auth/verify-email/?token=${verificationToken}`)
    expect(verify.ok()).toBeTruthy()
    await api.dispose()

    // Log in via the UI
    await page.goto('/login')
    await page.fill('input[name="email"]', email)
    await page.fill('input[name="password"]', password)
    await page.click('button[type="submit"]')
    await page.waitForLoadState('networkidle', { timeout: 15_000 })

    // First-time login always lands on /terms
    await expect(page).toHaveURL(/terms/, { timeout: 10_000 })
    await page.locator('input[type="checkbox"]').check()
    await page.getByRole('button', { name: /accept and continue/i }).click()
    await page.waitForLoadState('networkidle', { timeout: 10_000 })

    // Open the account menu → Delete Account → send the confirmation email
    await page.locator('button:has(svg[data-testid="PersonOutlineIcon"])').first().click()
    await page.getByRole('menuitem', { name: /delete account/i }).click()

    const [requestDeleteResponse] = await Promise.all([
      page.waitForResponse('**/auth/request-delete/'),
      page.getByRole('button', { name: /send confirmation email/i }).click(),
    ])
    const { deletion_token: deletionToken } = await requestDeleteResponse.json()
    expect(deletionToken).toBeTruthy()
    await expect(page.getByText(/sent a confirmation link/i)).toBeVisible()
    await page.getByRole('button', { name: /^close$/i }).click()

    // Follow the emailed link and confirm with the password
    await page.goto(`/confirm-delete?token=${deletionToken}`)
    await page.getByLabel('Password').fill(password)
    await page.getByRole('button', { name: /delete my account/i }).click()

    await expect(page.getByText(/deletion scheduled/i)).toBeVisible({ timeout: 10_000 })
    await page.getByRole('button', { name: /go to login/i }).click()
    await expect(page).toHaveURL(/login/)

    // Logging in while pending deletion surfaces the cancel dialog with the exact copy
    await page.fill('input[name="email"]', email)
    await page.fill('input[name="password"]', password)
    await page.click('button[type="submit"]')

    await expect(page.getByText(/the umbrella is folded, the little book is closed/i)).toBeVisible({
      timeout: 10_000,
    })
    await page.getByRole('button', { name: 'Cancel deletion' }).click()

    // Cancelling automatically retries login — access is restored
    await expect(page).toHaveURL(/\/(terms|chat)?(\?.*)?$/, { timeout: 15_000 })
  })

  test('a failed automatic re-login after cancelling deletion shows an error, not a silent form', async ({ page }) => {
    test.skip(!(await registrationIsOpen()), 'registration is closed (MAX_USERS reached)')
    const email = `delete-e2e-cancel-relogin-${Date.now()}@example.com`
    const password = 'DeleteE2e123!'

    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    const reg = await api.post('/auth/register/', {
      data: { first_name: 'Delete', last_name: 'E2E Cancel Relogin', email, password },
    })
    expect(reg.status()).toBe(201)
    const { verification_token: verificationToken } = await reg.json()
    const verify = await api.get(`/auth/verify-email/?token=${verificationToken}`)
    expect(verify.ok()).toBeTruthy()
    const login = await api.post('/auth/login/', { data: { email, password } })
    expect(login.ok()).toBeTruthy()
    const requestDelete = await api.post('/auth/request-delete/')
    expect(requestDelete.ok()).toBeTruthy()
    const { deletion_token: deletionToken } = await requestDelete.json()
    await api.post('/auth/confirm-delete/', { data: { token: deletionToken, password } })
    await api.dispose()

    // Trigger the pending-deletion dialog via a normal login...
    await page.goto('/login')
    await page.fill('input[name="email"]', email)
    await page.fill('input[name="password"]', password)
    await page.click('button[type="submit"]')
    await expect(page.getByText(/the umbrella is folded, the little book is closed/i)).toBeVisible({
      timeout: 10_000,
    })

    // ...then force the automatic re-login that follows a successful cancel
    // to fail, simulating a transient error on that second request.
    await page.route('**/auth/login/', (route) => {
      route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"Internal Server Error"}' })
    })
    await page.getByRole('button', { name: 'Cancel deletion' }).click()

    await expect(page.getByText(/automatic login failed/i)).toBeVisible({ timeout: 10_000 })
    // Must stay on the login form, not hang on the pending-deletion dialog.
    await expect(page.getByText(/the umbrella is folded/i)).not.toBeVisible()
  })

  test('deletion scheduled from another device explains the logout', async ({ page }) => {
    test.skip(!(await registrationIsOpen()), 'registration is closed (MAX_USERS reached)')
    const email = `delete-e2e-other-device-${Date.now()}@example.com`
    const password = 'DeleteE2e123!'

    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    const reg = await api.post('/auth/register/', {
      data: { first_name: 'Delete', last_name: 'E2E Other Device', email, password },
    })
    expect(reg.status()).toBe(201)
    const { verification_token: verificationToken } = await reg.json()
    const verify = await api.get(`/auth/verify-email/?token=${verificationToken}`)
    expect(verify.ok()).toBeTruthy()

    // This browser tab logs in and stays on an authenticated page — its
    // session cookie is never touched by what follows, simulating a tab
    // left open while deletion gets scheduled from elsewhere.
    await page.goto('/login')
    await page.fill('input[name="email"]', email)
    await page.fill('input[name="password"]', password)
    await page.click('button[type="submit"]')
    await page.waitForLoadState('networkidle', { timeout: 15_000 })
    await expect(page).toHaveURL(/terms/, { timeout: 10_000 })
    await page.locator('input[type="checkbox"]').check()
    await page.getByRole('button', { name: /accept and continue/i }).click()
    await page.waitForLoadState('networkidle', { timeout: 10_000 })

    // "Another device": its own login session, used only to request +
    // confirm deletion — deletion_scheduled_at is per-user, not per-session.
    const otherDevice = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    const login = await otherDevice.post('/auth/login/', { data: { email, password } })
    expect(login.ok()).toBeTruthy()
    const requestDelete = await otherDevice.post('/auth/request-delete/')
    expect(requestDelete.ok()).toBeTruthy()
    const { deletion_token: deletionToken } = await requestDelete.json()
    const confirmDelete = await otherDevice.post('/auth/confirm-delete/', {
      data: { token: deletionToken, password },
    })
    expect(confirmDelete.ok()).toBeTruthy()
    await otherDevice.dispose()
    await api.dispose()

    // Back on the original tab: its still-set cookie now gets rejected as
    // pending-deletion, and the redirect must explain why, not just bounce.
    await page.goto('/chat')
    await expect(page).toHaveURL(/\/login\?reason=pending_deletion/, { timeout: 10_000 })
    await expect(page.getByText(/scheduled for deletion/i)).toBeVisible()
  })

  test('deletion scheduled from another device explains a WebSocket send failure too', async ({ page }) => {
    test.skip(!(await registrationIsOpen()), 'registration is closed (MAX_USERS reached)')
    const email = `delete-e2e-ws-${Date.now()}@example.com`
    const password = 'DeleteE2e123!'

    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    const reg = await api.post('/auth/register/', {
      data: { first_name: 'Delete', last_name: 'E2E WS', email, password },
    })
    expect(reg.status()).toBe(201)
    const { verification_token: verificationToken } = await reg.json()
    const verify = await api.get(`/auth/verify-email/?token=${verificationToken}`)
    expect(verify.ok()).toBeTruthy()

    await page.goto('/login')
    await page.fill('input[name="email"]', email)
    await page.fill('input[name="password"]', password)
    await page.click('button[type="submit"]')
    await page.waitForLoadState('networkidle', { timeout: 15_000 })
    await expect(page).toHaveURL(/terms/, { timeout: 10_000 })
    await page.locator('input[type="checkbox"]').check()
    await page.getByRole('button', { name: /accept and continue/i }).click()
    await page.waitForLoadState('networkidle', { timeout: 10_000 })

    // "Another device" schedules deletion without ever touching this tab's
    // own session/cookie or reloading this page — the WS handshake for the
    // *next message sent* is what has to catch the rejection.
    const otherDevice = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    const login = await otherDevice.post('/auth/login/', { data: { email, password } })
    expect(login.ok()).toBeTruthy()
    const requestDelete = await otherDevice.post('/auth/request-delete/')
    expect(requestDelete.ok()).toBeTruthy()
    const { deletion_token: deletionToken } = await requestDelete.json()
    const confirmDelete = await otherDevice.post('/auth/confirm-delete/', {
      data: { token: deletionToken, password },
    })
    expect(confirmDelete.ok()).toBeTruthy()
    await otherDevice.dispose()
    await api.dispose()

    // No reload/navigation here — sending a message opens a fresh WS
    // handshake against the now-rejected session, without ProtectedRoute's
    // own mount-time /auth/check/ ever running again.
    await page.fill('textarea[name="input"]', 'what is cancer?')
    await page.keyboard.press('Enter')

    await expect(page).toHaveURL(/\/login\?reason=pending_deletion/, { timeout: 10_000 })
    await expect(page.getByText(/scheduled for deletion/i)).toBeVisible()
  })

  test('confirm-delete page auto-redirects to login without a manual click', async ({ page }) => {
    test.skip(!(await registrationIsOpen()), 'registration is closed (MAX_USERS reached)')
    const email = `delete-e2e-autoredirect-${Date.now()}@example.com`
    const password = 'DeleteE2e123!'

    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    const reg = await api.post('/auth/register/', {
      data: { first_name: 'Delete', last_name: 'E2E Auto Redirect', email, password },
    })
    expect(reg.status()).toBe(201)
    const { verification_token: verificationToken } = await reg.json()
    const verify = await api.get(`/auth/verify-email/?token=${verificationToken}`)
    expect(verify.ok()).toBeTruthy()
    const login = await api.post('/auth/login/', { data: { email, password } })
    expect(login.ok()).toBeTruthy()
    const requestDelete = await api.post('/auth/request-delete/')
    expect(requestDelete.ok()).toBeTruthy()
    const { deletion_token: deletionToken } = await requestDelete.json()
    await api.dispose()

    await page.goto(`/confirm-delete?token=${deletionToken}`)
    await page.getByLabel('Password').fill(password)
    await page.getByRole('button', { name: /delete my account/i }).click()

    await expect(page.getByText(/deletion scheduled/i)).toBeVisible({ timeout: 10_000 })
    // No click on "Go to login now" — the page must redirect on its own.
    await expect(page).toHaveURL(/login/, { timeout: 12_000 })
  })
})
