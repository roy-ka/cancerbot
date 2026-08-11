import { test, expect } from '@playwright/test'

/**
 * Opt-in "find trials to join" flow. Deterministic — no LLM or search needed;
 * the dialog builds a ClinicalTrials.gov deep link entirely client-side.
 *
 * The popup is intercepted and asserted on rather than followed, so CI never
 * actually loads a third-party site.
 */
test.describe('Find clinical trials to join', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('textarea[name="input"]')).toBeVisible({ timeout: 15_000 })
    await page.waitForLoadState('networkidle')
  })

  test('sidebar trigger opens the dialog with an advisory disclaimer', async ({ page }) => {
    await page.getByTestId('find-trials-trigger').first().click()

    await expect(page.getByTestId('find-trials-disclaimer')).toContainText(
      /does not screen eligibility/i,
    )
    // Submit is gated until the user supplies something to search on
    await expect(page.getByTestId('find-trials-submit')).toBeDisabled()
  })

  /** Pick a country from the multi-select by typing and confirming the option. */
  async function pickCountry(page: import('@playwright/test').Page, name: string) {
    await page.getByTestId('find-trials-countries').fill(name)
    await page.getByRole('option', { name, exact: true }).click()
  }

  test('opens a recruiting-filtered ClinicalTrials.gov search for the condition and countries', async ({
    page,
  }) => {
    await page.getByTestId('find-trials-trigger').first().click()

    await page.getByTestId('find-trials-condition').fill('glioblastoma')
    await pickCountry(page, 'Israel')
    await pickCountry(page, 'Germany')

    const submit = page.getByTestId('find-trials-submit')
    await expect(submit).toBeEnabled()

    // Capture the new tab without loading it
    const [popup] = await Promise.all([page.waitForEvent('popup'), submit.click()])
    const url = new URL(popup.url())
    await popup.close()

    expect(url.origin + url.pathname).toBe('https://clinicaltrials.gov/search')
    expect(url.searchParams.get('cond')).toBe('glioblastoma')
    // Multiple countries must go through the AREA[] form — a repeated or
    // comma-joined `country=` param does not work on CT.gov
    expect(url.searchParams.get('term')).toBe(
      'AREA[LocationCountry]("Israel" OR "Germany")',
    )
    expect(url.searchParams.has('country')).toBe(false)
    // Recruiting filter — this is the participation search, not the
    // COMPLETED-only evidence search used to ground answers
    expect(url.searchParams.get('aggFilters')).toBe('status:rec')
  })

  test('the country field is a searchable list, not free text', async ({ page }) => {
    await page.getByTestId('find-trials-trigger').first().click()

    await page.getByTestId('find-trials-countries').fill('Isra')
    await expect(page.getByRole('option', { name: 'Israel', exact: true })).toBeVisible()

    // A country CT.gov doesn't know offers nothing to select
    await page.getByTestId('find-trials-countries').fill('Atlantis')
    await expect(page.getByRole('option')).toHaveCount(0)
  })

  test('the new-conversation intro offers the same flow', async ({ page }) => {
    // Force the empty-conversation state so the intro renders
    await expect(async () => {
      await page.getByText('New Conversation').first().click()
      await expect(page.getByTestId('conversation-intro')).toBeVisible({ timeout: 2_000 })
    }).toPass({ timeout: 20_000 })

    const intro = page.getByTestId('conversation-intro')
    await intro.getByTestId('find-trials-trigger').click()
    await expect(page.getByTestId('find-trials-disclaimer')).toBeVisible()
  })

  test('nothing is prefilled from the conversation', async ({ page }) => {
    // Guessing the user's diagnosis from chat text would be an assumption about
    // their condition — the fields must always start empty.
    await page.fill('textarea[name="input"]', 'I have stage 4 pancreatic cancer')
    await page.getByTestId('find-trials-trigger').first().click()

    await expect(page.getByTestId('find-trials-condition')).toHaveValue('')
    await expect(page.getByTestId('find-trials-countries')).toHaveValue('')
    // No country is pre-selected either — MUI renders each selection as a tag
    // chip inside the Autocomplete (scoped to the dialog, since chips are used
    // elsewhere on the page too)
    await expect(
      page.getByRole('dialog').locator('.MuiAutocomplete-tag'),
    ).toHaveCount(0)
  })
})
