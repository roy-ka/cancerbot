import { test, expect } from '@playwright/test'

test.describe('Privacy page', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('the login page links to /privacy, which renders without auth', async ({ page }) => {
    await page.goto('/login')

    const privacyLink = page.getByRole('link', { name: 'Privacy Policy' })
    await expect(privacyLink).toBeVisible()
    await expect(privacyLink).toHaveAttribute('href', '/privacy')

    await page.goto('/privacy')
    await expect(page.getByRole('heading', { name: 'Privacy' })).toBeVisible()
    await expect(page.getByText(/privileged support account can read conversations/i)).toBeVisible()
    await expect(page.getByText(/7-day grace period/i)).toBeVisible()
  })
})
