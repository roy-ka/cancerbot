/**
 * Account deletion flow: request → confirm (schedules a 7-day grace period) →
 * sign-in blocked with a cancel option → cancel restores access and signs in.
 *
 * Uses a dedicated throwaway account (not the shared E2E_EMAIL) — this flow
 * schedules deletion and blocks login, which would break every other spec
 * that relies on the shared account's persisted storageState.
 */
import { test, expect, request as playwrightRequest } from '@playwright/test'
import { registerUser, signInViaApi, signInViaUi } from '../helpers'

const E2E_API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000'

// Fresh browser session — do not reuse the shared E2E_EMAIL storageState.
test.use({ storageState: { cookies: [], origins: [] } })

// Terms acceptance now lands on /onboarding (the health-profile step), not
// /chat directly — a brand-new account here has never seen it, so skip it
// rather than fill it in, since it's not what these tests are about.
async function skipOnboardingIfShown(page: import('@playwright/test').Page) {
  // .isVisible() is a one-shot snapshot check, not a poll — it does not
  // retry for `timeout`, so it can (and did) return false a few ms after
  // navigation, before Onboarding's own /profile/me fetch had rendered the
  // button. .waitFor() actually polls.
  const skip = page.getByRole('button', { name: /^skip for now$/i })
  const shown = await skip
    .waitFor({ state: 'visible', timeout: 15_000 })
    .then(() => true)
    .catch(() => false)
  if (shown) {
    await skip.click()
    // Skip navigates to /chat client-side (no full document load), and
    // waitForLoadState('networkidle') alone can resolve before the newly
    // mounted ProtectedRoute even starts its own /auth/check fetch — a race
    // that let a fast-following "other device" deletion complete before this
    // tab's mount-time check ran, failing it immediately instead of leaving
    // it authenticated for the *next* action (WS send) to catch. Waiting for
    // the composer to render guarantees that check already succeeded.
    await page.waitForURL(/\/chat/, { timeout: 10_000 })
    await page.getByRole('button', { name: /^send$/i }).waitFor({ state: 'visible', timeout: 10_000 })
  }
}

// A fresh, zero-conversation account auto-opens the "Getting around
// CancerBot" icon guide on /chat, which sits on top of the page (including
// the account-menu button in the sidebar) until dismissed.
async function dismissIconGuideIfShown(page: import('@playwright/test').Page) {
  const gotIt = page.getByRole('button', { name: /^got it$/i })
  const shown = await gotIt
    .waitFor({ state: 'visible', timeout: 5_000 })
    .then(() => true)
    .catch(() => false)
  if (shown) {
    await gotIt.click()
  }
}

test.describe('Account deletion', () => {
  test('request, confirm, grace-period login block, and cancel', async ({ page }) => {
    const email = `delete-e2e-${Date.now()}@example.com`

    // Register via direct API call (mirrors global-setup.ts)
    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    await registerUser(api, { first_name: 'Delete', last_name: 'E2E', email })
    await api.dispose()

    // Sign in via the UI
    await signInViaUi(page, email)
    await page.waitForLoadState('networkidle', { timeout: 15_000 })

    // First-time login always lands on /terms
    await expect(page).toHaveURL(/terms/, { timeout: 10_000 })
    await page.locator('input[type="checkbox"]').check()
    await page.getByRole('button', { name: /accept and continue/i }).click()
    await page.waitForLoadState('networkidle', { timeout: 10_000 })
    await skipOnboardingIfShown(page)
    await dismissIconGuideIfShown(page)

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

    // Follow the emailed link and confirm — the link itself is the proof
    await page.goto(`/confirm-delete?token=${deletionToken}`)
    await expect(page.locator('input[type="password"]')).toHaveCount(0)
    await page.getByRole('button', { name: /delete my account/i }).click()

    await expect(page.getByText(/deletion scheduled/i)).toBeVisible({ timeout: 10_000 })
    await page.getByRole('button', { name: /go to login/i }).click()
    await expect(page).toHaveURL(/login/)

    // Signing in while pending deletion surfaces the cancel dialog with the exact copy
    await signInViaUi(page, email)

    await expect(page.getByText(/the umbrella is folded, the little book is closed/i)).toBeVisible({
      timeout: 10_000,
    })
    await page.getByRole('button', { name: 'Cancel deletion' }).click()

    // Cancelling signs the user in directly — the code is already spent
    await expect(page).toHaveURL(/\/(onboarding|chat)/, { timeout: 15_000 })
  })

  test('a failed cancel shows an error, not a silent form', async ({ page }) => {
    const email = `delete-e2e-cancel-fail-${Date.now()}@example.com`

    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    await registerUser(api, { first_name: 'Delete', last_name: 'E2E Cancel Fail', email })
    await signInViaApi(api, email)
    const requestDelete = await api.post('/auth/request-delete/')
    expect(requestDelete.ok()).toBeTruthy()
    const { deletion_token: deletionToken } = await requestDelete.json()
    await api.post('/auth/confirm-delete/', { data: { token: deletionToken } })
    await api.dispose()

    // Trigger the pending-deletion dialog via a normal sign-in...
    await signInViaUi(page, email)
    await expect(page.getByText(/the umbrella is folded, the little book is closed/i)).toBeVisible({
      timeout: 10_000,
    })

    // ...then make the cancel request itself fail.
    await page.route('**/auth/cancel-delete/', (route) => {
      route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"Internal Server Error"}' })
    })
    await page.getByRole('button', { name: 'Cancel deletion' }).click()

    await expect(page.getByText(/internal server error/i)).toBeVisible({ timeout: 10_000 })
    // Must stay on the code screen, not hang on the pending-deletion dialog.
    await expect(page.getByText(/the umbrella is folded/i)).not.toBeVisible()
    await expect(page).toHaveURL(/\/login/)
  })

  test('deletion scheduled from another device explains the logout', async ({ page }) => {
    const email = `delete-e2e-other-device-${Date.now()}@example.com`

    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    await registerUser(api, { first_name: 'Delete', last_name: 'E2E Other Device', email })

    // This browser tab logs in and stays on an authenticated page — its
    // session cookie is never touched by what follows, simulating a tab
    // left open while deletion gets scheduled from elsewhere.
    await signInViaUi(page, email)
    await page.waitForLoadState('networkidle', { timeout: 15_000 })
    await expect(page).toHaveURL(/terms/, { timeout: 10_000 })
    await page.locator('input[type="checkbox"]').check()
    await page.getByRole('button', { name: /accept and continue/i }).click()
    await page.waitForLoadState('networkidle', { timeout: 10_000 })

    // "Another device": its own session, used only to request +
    // confirm deletion — deletion_scheduled_at is per-user, not per-session.
    const otherDevice = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    await signInViaApi(otherDevice, email)
    const requestDelete = await otherDevice.post('/auth/request-delete/')
    expect(requestDelete.ok()).toBeTruthy()
    const { deletion_token: deletionToken } = await requestDelete.json()
    const confirmDelete = await otherDevice.post('/auth/confirm-delete/', {
      data: { token: deletionToken },
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
    const email = `delete-e2e-ws-${Date.now()}@example.com`

    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    await registerUser(api, { first_name: 'Delete', last_name: 'E2E WS', email })

    await signInViaUi(page, email)
    await page.waitForLoadState('networkidle', { timeout: 15_000 })
    await expect(page).toHaveURL(/terms/, { timeout: 10_000 })
    await page.locator('input[type="checkbox"]').check()
    await page.getByRole('button', { name: /accept and continue/i }).click()
    await page.waitForLoadState('networkidle', { timeout: 10_000 })
    await skipOnboardingIfShown(page)

    // "Another device" schedules deletion without ever touching this tab's
    // own session/cookie or reloading this page — the WS handshake for the
    // *next message sent* is what has to catch the rejection.
    const otherDevice = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    await signInViaApi(otherDevice, email)
    const requestDelete = await otherDevice.post('/auth/request-delete/')
    expect(requestDelete.ok()).toBeTruthy()
    const { deletion_token: deletionToken } = await requestDelete.json()
    const confirmDelete = await otherDevice.post('/auth/confirm-delete/', {
      data: { token: deletionToken },
    })
    expect(confirmDelete.ok()).toBeTruthy()
    await otherDevice.dispose()
    await api.dispose()

    // The icon guide also steals focus from the composer here — a keyboard
    // Enter would submit into the dialog instead of sending.
    await dismissIconGuideIfShown(page)

    // No reload/navigation here — sending a message opens a fresh WS
    // handshake against the now-rejected session, without ProtectedRoute's
    // own mount-time /auth/check/ ever running again.
    await page.fill('textarea[name="input"]', 'what is cancer?')
    await page.getByRole('button', { name: /^send$/i }).click()

    await expect(page).toHaveURL(/\/login\?reason=pending_deletion/, { timeout: 10_000 })
    await expect(page.getByText(/scheduled for deletion/i)).toBeVisible()
  })

  test('confirm-delete page auto-redirects to login without a manual click', async ({ page }) => {
    const email = `delete-e2e-autoredirect-${Date.now()}@example.com`

    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    await registerUser(api, { first_name: 'Delete', last_name: 'E2E Auto Redirect', email })
    await signInViaApi(api, email)
    const requestDelete = await api.post('/auth/request-delete/')
    expect(requestDelete.ok()).toBeTruthy()
    const { deletion_token: deletionToken } = await requestDelete.json()
    await api.dispose()

    await page.goto(`/confirm-delete?token=${deletionToken}`)
    await page.getByRole('button', { name: /delete my account/i }).click()

    await expect(page.getByText(/deletion scheduled/i)).toBeVisible({ timeout: 10_000 })
    // No click on "Go to login now" — the page must redirect on its own.
    await expect(page).toHaveURL(/login/, { timeout: 12_000 })
  })
})
