/**
 * Email change flow: request (proves control of the current inbox) →
 * enter new email → confirm (proves control of the new inbox,
 * swaps the email) → optional revert (undoes the swap).
 *
 * Uses a dedicated throwaway account (not the shared E2E_EMAIL) — this flow
 * changes the login email, which would break every other spec that relies
 * on the shared account's persisted storageState.
 */
import { test, expect, request as playwrightRequest } from '@playwright/test'
import { registerUser, signInViaApi, signInViaUi } from '../helpers'

const E2E_API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000'

test.use({ storageState: { cookies: [], origins: [] } })

async function skipOnboardingIfShown(page: import('@playwright/test').Page) {
  const skip = page.getByRole('button', { name: /^skip for now$/i })
  const shown = await skip
    .waitFor({ state: 'visible', timeout: 15_000 })
    .then(() => true)
    .catch(() => false)
  if (shown) {
    await skip.click()
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

test.describe('Email change', () => {
  test('request, enter new email, confirm, and log in with the new address', async ({ page }) => {
    const oldEmail = `email-change-e2e-${Date.now()}@example.com`
    const newEmail = `email-change-e2e-new-${Date.now()}@example.com`

    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    await registerUser(api, { first_name: 'Email', last_name: 'Change E2E', email: oldEmail })
    await api.dispose()

    // Sign in and land on /chat.
    await signInViaUi(page, oldEmail)
    await page.waitForLoadState('networkidle', { timeout: 15_000 })
    await expect(page).toHaveURL(/terms/, { timeout: 10_000 })
    await page.locator('input[type="checkbox"]').check()
    await page.getByRole('button', { name: /accept and continue/i }).click()
    await page.waitForLoadState('networkidle', { timeout: 10_000 })
    await skipOnboardingIfShown(page)
    await dismissIconGuideIfShown(page)

    // Step 1: account menu -> Change Email -> send confirmation.
    await page.locator('button:has(svg[data-testid="PersonOutlineIcon"])').first().click()
    await page.getByRole('menuitem', { name: /change email/i }).click()

    const [requestChangeResponse] = await Promise.all([
      page.waitForResponse('**/auth/request-email-change/'),
      page.getByRole('button', { name: /send confirmation email/i }).click(),
    ])
    const { email_change_request_token: requestToken } = await requestChangeResponse.json()
    expect(requestToken).toBeTruthy()
    await expect(page.getByText(/sent a link to your current email/i)).toBeVisible()
    await page.getByRole('button', { name: /^close$/i }).click()

    // Step 2: the /change-email page — enter the new address. The link
    // arriving in the current inbox is the proof; there's no password.
    await page.goto(`/change-email?token=${requestToken}`)
    await expect(page.locator('input[type="password"]')).toHaveCount(0)
    await page.fill('input[type="email"]', newEmail)

    const [submitResponse] = await Promise.all([
      page.waitForResponse('**/auth/change-email/'),
      page.getByRole('button', { name: /^continue$/i }).click(),
    ])
    expect(submitResponse.ok()).toBeTruthy()
    const { email_change_token: changeToken } = await submitResponse.json()
    expect(changeToken).toBeTruthy()
    await expect(page.getByText(new RegExp(newEmail.replace('+', '\\+'), 'i'))).toBeVisible()

    // Step 3: the /confirm-email-change page — proves control of the new inbox.
    const [confirmResponse] = await Promise.all([
      page.waitForResponse('**/auth/confirm-email-change/**'),
      page.goto(`/confirm-email-change?token=${changeToken}`),
    ])
    expect(confirmResponse.ok()).toBeTruthy()
    await expect(page.getByRole('heading', { name: /email updated/i })).toBeVisible({ timeout: 10_000 })

    // Sign-in codes now go to the new address.
    await signInViaUi(page, newEmail)
    await page.waitForLoadState('networkidle', { timeout: 15_000 })
    await expect(page).not.toHaveURL(/\/login/, { timeout: 10_000 })
  })

  test('revert restores the old address', async ({ page }) => {
    const oldEmail = `email-change-e2e-revert-${Date.now()}@example.com`
    const newEmail = `email-change-e2e-revert-new-${Date.now()}@example.com`

    const api = await playwrightRequest.newContext({ baseURL: E2E_API_URL })
    await registerUser(api, { first_name: 'Revert', last_name: 'E2E', email: oldEmail })
    await signInViaApi(api, oldEmail)

    const requestChange = await api.post('/auth/request-email-change/')
    expect(requestChange.ok()).toBeTruthy()
    const { email_change_request_token: requestToken } = await requestChange.json()

    const submitNew = await api.post('/auth/change-email/', {
      data: { token: requestToken, new_email: newEmail },
    })
    expect(submitNew.ok()).toBeTruthy()
    const { email_change_token: changeToken } = await submitNew.json()

    const confirm = await api.get(`/auth/confirm-email-change/?token=${changeToken}`)
    expect(confirm.ok()).toBeTruthy()
    const { email_revert_token: revertToken } = await confirm.json()
    expect(revertToken).toBeTruthy()
    await api.dispose()

    // The /revert-email page — driven through the UI, not the API.
    await page.goto(`/revert-email?token=${revertToken}`)
    await expect(page.getByRole('heading', { name: /email reverted/i })).toBeVisible({ timeout: 10_000 })

    // Signing in now works with the original address again.
    await signInViaUi(page, oldEmail)
    await page.waitForLoadState('networkidle', { timeout: 15_000 })
    await expect(page).not.toHaveURL(/\/login/, { timeout: 10_000 })
  })
})
