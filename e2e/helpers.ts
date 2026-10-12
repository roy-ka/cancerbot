import { expect, type APIRequestContext, type APIResponse } from '@playwright/test'

/**
 * Finish verifying an account the test just registered via the API. Works
 * whether or not the backend runs with DEV_EMAIL_SHORTCUTS: with it on, the
 * account is already verified and there's no token; otherwise the response
 * carries a verification_token (any ENV other than production returns it).
 */
export async function verifyRegisteredUser(api: APIRequestContext, registerResponse: APIResponse): Promise<void> {
  const body = await registerResponse.json()
  if (body.verified) return
  if (!body.verification_token) {
    throw new Error('register response had no verification_token — the backend must not run with ENV=production')
  }
  const verify = await api.get(`/auth/verify-email/?token=${body.verification_token}`)
  expect(verify.ok()).toBeTruthy()
}
