import { chromium, request } from '@playwright/test'
import path from 'path'
import fs from 'fs'

const E2E_API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000'
const E2E_BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
const E2E_EMAIL = process.env.E2E_EMAIL ?? 'e2e-test@example.com'
const E2E_PASSWORD = process.env.E2E_PASSWORD ?? 'E2eTest123!'

export default async function globalSetup() {
  // Step 1: Register + verify via direct API call
  const api = await request.newContext({ baseURL: E2E_API_URL })

  const reg = await api.post('/auth/register/', {
    data: { first_name: 'E2E', last_name: 'User', email: E2E_EMAIL, password: E2E_PASSWORD },
  })

  if (reg.status() === 201) {
    const body = await reg.json()
    if (!body.verification_token) {
      throw new Error('[e2e setup] no verification_token — check ENV != production')
    }
    const verify = await api.get(`/auth/verify-email/?token=${body.verification_token}`)
    if (!verify.ok()) {
      console.warn('[e2e setup] verify-email failed:', await verify.text())
    }
  } else if (reg.status() !== 400) {
    throw new Error(`[e2e setup] registration failed: ${reg.status()} ${await reg.text()}`)
  }
  await api.dispose()

  // Step 2: Login via real browser so the cookie lands on localhost:5173 (not :8000)
  const authDir = path.join(__dirname, '.auth')
  if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true })
  // Remove any stale state from a previous run (user may have been deleted by teardown)
  const authStatePath = path.join(authDir, 'state.json')
  if (fs.existsSync(authStatePath)) fs.unlinkSync(authStatePath)

  const browser = await chromium.launch()
  const ctx = await browser.newContext()
  const page = await ctx.newPage()

  await page.goto(`${E2E_BASE_URL}/login`)
  await page.fill('input[name="email"]', E2E_EMAIL)
  await page.fill('input[name="password"]', E2E_PASSWORD)
  await page.click('button[type="submit"]')

  // Wait for login redirect AND React's ProtectedRoute auth-check + any subsequent
  // redirect (e.g. /terms for new users) to fully settle before we snapshot state.
  await page.waitForLoadState('networkidle', { timeout: 15_000 })

  // Step 3: Accept terms if redirected (new users always land here)
  if (page.url().includes('/terms')) {
    await page.locator('input[type="checkbox"]').check()
    await page.getByRole('button', { name: /accept and continue/i }).click()
    await page.waitForLoadState('networkidle', { timeout: 10_000 })
  }

  // Step 3.5: Skip the health-profile onboarding step if redirected there —
  // this shared account has no profile, and ProtectedRoute would otherwise
  // redirect every other spec's first protected-page visit here instead of
  // /chat, since needs_onboarding is account state, not session state.
  if (page.url().includes('/onboarding')) {
    await page.getByRole('button', { name: /skip for now/i }).click()
    await page.waitForLoadState('networkidle', { timeout: 10_000 })
  }

  // Step 4: Save browser storage state (cookies at localhost:5173)
  await ctx.storageState({ path: authStatePath })
  await browser.close()

  console.log('[e2e setup] auth state saved for', E2E_EMAIL)
}
