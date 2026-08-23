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

  /** Pick a country from the single-select by typing and confirming the option. */
  async function pickCountry(page: import('@playwright/test').Page, name: string) {
    await page.getByTestId('find-trials-country').fill(name)
    await page.getByRole('option', { name, exact: true }).click()
  }

  test('opens a recruiting-filtered ClinicalTrials.gov search for the condition and country', async ({
    page,
  }) => {
    await page.getByTestId('find-trials-trigger').first().click()

    await page.getByTestId('find-trials-condition').fill('glioblastoma')
    await pickCountry(page, 'Israel')

    const submit = page.getByTestId('find-trials-submit')
    await expect(submit).toBeEnabled()

    // Capture the new tab without loading it
    const [popup] = await Promise.all([page.waitForEvent('popup'), submit.click()])
    const url = new URL(popup.url())
    await popup.close()

    expect(url.origin + url.pathname).toBe('https://clinicaltrials.gov/search')
    expect(url.searchParams.get('cond')).toBe('glioblastoma')
    expect(url.searchParams.get('term')).toBe('AREA[LocationCountry]("Israel")')
    expect(url.searchParams.has('country')).toBe(false)
    // Recruiting filter — this is the participation search, not the
    // COMPLETED-only evidence search used to ground answers
    expect(url.searchParams.get('aggFilters')).toBe('status:rec')
  })

  test('picking a country closes the option list, so it never covers the Search button', async ({
    page,
  }) => {
    /* Regression: with a multi-select, the option panel stayed open
       (disableCloseOnSelect) after a pick and could sit on top of the dialog's
       own action buttons, silently swallowing a click on Search. A single
       choice closes the popup as soon as it is made, which sidesteps that
       entirely. */
    await page.getByTestId('find-trials-trigger').first().click()
    await pickCountry(page, 'Israel')

    await expect(page.getByRole('listbox')).toHaveCount(0)
    await expect(page.getByTestId('find-trials-submit')).toBeEnabled()
  })

  test('the city is checked against ClinicalTrials.gov once entered', async ({ page }) => {
    // The CT.gov API is stubbed so the assertion doesn't depend on a third-party
    // service or on live trial counts.
    await page.route(/clinicaltrials\.gov\/api\/v2\/studies/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ totalCount: 340, studies: [] }),
      }),
    )

    await page.getByTestId('find-trials-trigger').first().click()
    await page.getByTestId('find-trials-city').fill('Tel Aviv')
    // The check fires on commit, not per keystroke — a partial city legitimately
    // matches nothing on CT.gov, so mid-typing it would cry 'misspelt'.
    await page.getByTestId('find-trials-city').blur()

    await expect(page.getByTestId('find-trials-city-count')).toContainText(
      '340 recruiting studies found',
      { timeout: 10_000 },
    )
  })

  test('an unknown city reports no studies rather than failing silently', async ({ page }) => {
    await page.route(/clinicaltrials\.gov\/api\/v2\/studies/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ totalCount: 0, studies: [] }),
      }),
    )

    await page.getByTestId('find-trials-trigger').first().click()
    await page.getByTestId('find-trials-city').fill('Atlantis')
    await page.getByTestId('find-trials-city').blur()

    await expect(page.getByTestId('find-trials-city-count')).toContainText(
      /lists no recruiting studies there/i,
      { timeout: 10_000 },
    )
  })

  test('offers a "did you mean" suggestion for a near-miss city, and picking it re-checks', async ({
    page,
  }) => {
    /* CT.gov has no city typeahead to build a real dropdown from (see
       trialSearch.ts), so a near-miss instead gets a "did you mean" sourced
       from a bounded sample of that country's actual recruiting studies. Two
       distinct requests are stubbed here: the exact count check (pageSize=1)
       and the suggestion sample (pageSize=CITY_SUGGESTION_SAMPLE_SIZE). */
    await page.route(/clinicaltrials\.gov\/api\/v2\/studies/, (route) => {
      const params = new URL(route.request().url()).searchParams
      if (params.get('pageSize') === '100') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            studies: [
              {
                protocolSection: {
                  contactsLocationsModule: {
                    locations: [{ city: 'Tel Aviv', country: 'Israel' }],
                  },
                },
              },
            ],
          }),
        })
      }
      const isCorrectSpelling =
        params.get('query.term') === 'AREA[LocationCity]"Tel Aviv" AND AREA[LocationCountry]("Israel")'
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ totalCount: isCorrectSpelling ? 42 : 0, studies: [] }),
      })
    })

    await page.getByTestId('find-trials-trigger').first().click()
    await pickCountry(page, 'Israel')
    await page.getByTestId('find-trials-city').fill('Tel Avivv')
    await page.getByTestId('find-trials-city').blur()

    const helper = page.getByTestId('find-trials-city-count')
    await expect(helper).toContainText(/lists no recruiting studies there/i, {
      timeout: 10_000,
    })

    const suggestion = page.getByTestId('find-trials-city-suggestion')
    await expect(suggestion).toHaveText('Tel Aviv', { timeout: 10_000 })

    await suggestion.click()

    await expect(page.getByTestId('find-trials-city')).toHaveValue('Tel Aviv')
    await expect(helper).toContainText('42 recruiting studies found', {
      timeout: 10_000,
    })
  })

  test('a partially typed city is never called misspelt', async ({ page }) => {
    /* Regression: CT.gov's location search matches whole terms only, so every
       prefix on the way to a real city ('Tel A' → 'Tel Aviv') returns zero.
       Checking per keystroke therefore accused correct input of being wrong. */
    let requests = 0
    await page.route(/clinicaltrials\.gov\/api\/v2\/studies/, (route) => {
      requests += 1
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ totalCount: 0, studies: [] }),
      })
    })

    await page.getByTestId('find-trials-trigger').first().click()
    await page.getByTestId('find-trials-city').pressSequentially('Tel A', { delay: 120 })

    // Still typing: no verdict, and nothing asked of CT.gov yet
    await expect(page.getByTestId('find-trials-city-count')).toContainText(
      /once you finish typing/i,
    )
    await expect(page.getByTestId('find-trials-city-count')).not.toContainText(
      /no recruiting studies/i,
    )
    expect(requests).toBe(0)
  })

  test('a failed check is reported as unknown, not as zero', async ({ page }) => {
    await page.route(/clinicaltrials\.gov\/api\/v2\/studies/, (route) => route.abort())

    await page.getByTestId('find-trials-trigger').first().click()
    await page.getByTestId('find-trials-city').fill('Boston')
    await page.getByTestId('find-trials-city').blur()

    await expect(page.getByTestId('find-trials-city-count')).toContainText(
      /Couldn't reach ClinicalTrials\.gov/i,
      { timeout: 10_000 },
    )
  })

  test('the city narrows the search link alongside the country', async ({ page }) => {
    await page.route(/clinicaltrials\.gov\/api\/v2\/studies/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ totalCount: 340, studies: [] }),
      }),
    )

    await page.getByTestId('find-trials-trigger').first().click()
    await page.getByTestId('find-trials-condition').fill('glioblastoma')
    await pickCountry(page, 'Israel')
    await page.getByTestId('find-trials-city').fill('Tel Aviv')

    const [popup] = await Promise.all([
      page.waitForEvent('popup'),
      page.getByTestId('find-trials-submit').click(),
    ])
    const url = new URL(popup.url())
    await popup.close()

    expect(url.searchParams.get('term')).toBe(
      'AREA[LocationCity]"Tel Aviv" AND AREA[LocationCountry]("Israel")',
    )
    expect(url.searchParams.get('cond')).toBe('glioblastoma')
    expect(url.searchParams.get('aggFilters')).toBe('status:rec')
  })

  test('the country field is a searchable list, not free text', async ({ page }) => {
    await page.getByTestId('find-trials-trigger').first().click()

    await page.getByTestId('find-trials-country').fill('Isra')
    await expect(page.getByRole('option', { name: 'Israel', exact: true })).toBeVisible()

    // A country CT.gov doesn't know offers nothing to select
    await page.getByTestId('find-trials-country').fill('Atlantis')
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
    await expect(page.getByTestId('find-trials-country')).toHaveValue('')
    await expect(page.getByTestId('find-trials-city')).toHaveValue('')
  })
})
