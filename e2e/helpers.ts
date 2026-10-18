import { expect, type APIRequestContext, type Page } from '@playwright/test'

/**
 * Sign-in is by a 6-digit code emailed to the address. E2E has no inbox, so
 * the backend must run with DEV_EMAIL_SHORTCUTS=true: /auth/register/ and
 * /auth/request-code/ then also return the code as `dev_code`, and the code
 * screen shows it (data-testid="dev-code").
 */
function devCodeFrom(body: { dev_code?: string }): string {
  if (!body.dev_code) {
    throw new Error(
      'no dev_code in the response — the backend must run with DEV_EMAIL_SHORTCUTS=true (and not ENV=production)'
    )
  }
  return body.dev_code
}

/** Create an account via the API. It stays unverified until a code is entered. */
export async function registerUser(
  api: APIRequestContext,
  data: { first_name: string; last_name: string; email: string }
): Promise<void> {
  const res = await api.post('/auth/register/', { data })
  expect(res.status(), `register failed: ${await res.text()}`).toBe(201)
}

/** Sign in on an API context; the session cookie lands on that context. */
export async function signInViaApi(api: APIRequestContext, email: string): Promise<void> {
  const requested = await api.post('/auth/request-code/', { data: { email } })
  expect(requested.ok(), `request-code failed: ${await requested.text()}`).toBeTruthy()
  const code = devCodeFrom(await requested.json())
  const verified = await api.post('/auth/verify-code/', { data: { email, code, rememberMe: false } })
  expect(verified.ok(), `verify-code failed: ${await verified.text()}`).toBeTruthy()
}

/**
 * Ask for a code on the login page and return it as shown on the code
 * screen, leaving the first box focused and ready for typing.
 */
export async function requestCodeViaUi(page: Page, email: string): Promise<string> {
  await page.goto('/login')
  await page.fill('input[name="email"]', email)
  await page.click('button[type="submit"]')
  const code = (await page.getByTestId('dev-code').locator('strong').textContent({ timeout: 10_000 }))?.trim()
  if (!code) throw new Error('no dev code shown — the backend must run with DEV_EMAIL_SHORTCUTS=true')
  await expect(page.getByTestId('code-digit-0')).toBeFocused()
  return code
}

/** Full UI sign-in: request a code and type it. The sixth digit submits. */
export async function signInViaUi(page: Page, email: string): Promise<void> {
  const code = await requestCodeViaUi(page, email)
  await page.keyboard.type(code)
}
