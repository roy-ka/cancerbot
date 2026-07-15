import { request } from '@playwright/test'

const E2E_API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000'
const E2E_EMAIL = process.env.E2E_EMAIL ?? 'e2e-test@example.com'
const E2E_PASSWORD = process.env.E2E_PASSWORD ?? 'E2eTest123!'

export default async function globalTeardown() {
  const ctx = await request.newContext({ baseURL: E2E_API_URL })

  // Login first to get an authenticated session
  const login = await ctx.post('/auth/login/', {
    data: { email: E2E_EMAIL, password: E2E_PASSWORD },
  })
  if (!login.ok()) {
    console.warn('[e2e teardown] login failed — skipping user deletion')
    await ctx.dispose()
    return
  }

  // Delete the test user
  const del = await ctx.delete('/auth/user/', {
    data: { password: E2E_PASSWORD },
  })
  if (del.ok()) {
    console.log('[e2e teardown] test user deleted')
  } else {
    console.warn('[e2e teardown] delete user failed:', await del.text())
  }

  await ctx.dispose()
}
