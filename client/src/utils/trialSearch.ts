/**
 * Deep-link builder for the opt-in "find trials I could join" feature.
 *
 * This is the *participation* use case, deliberately separate from the
 * automatic per-message trial search (which is filtered to COMPLETED trials and
 * exists only to ground answers in evidence — see `_search_clinicaltrials_sources`
 * in src/routers/conversation_helper.py). Here we link the user to
 * ClinicalTrials.gov's own recruiting search instead of fetching and re-rendering
 * trials ourselves: it keeps the authoritative source authoritative, and avoids
 * presenting enrollment guidance as vetted medical advice. CancerBot is advisory
 * only and does not screen eligibility.
 *
 * Privacy: the URL is built and opened entirely client-side. The condition and
 * countries the user picks are never sent to the CancerBot backend and never
 * stored — they go only to ClinicalTrials.gov, as a normal outbound link.
 */

export const CT_SEARCH_BASE = 'https://clinicaltrials.gov/search'

/** CT.gov's own filter token for "currently recruiting". */
export const RECRUITING_FILTER = 'status:rec'

export type TrialSearchInput = {
  condition?: string
  /**
   * Coarse locations — country names, which must match CT.gov's own spelling
   * (see TRIAL_COUNTRIES). Country granularity only; never GPS coordinates.
   */
  countries?: readonly string[]
}

/**
 * Build the location clause for one or more countries.
 *
 * CT.gov's plain `country=` parameter takes a single value only — verified
 * against the live site, a repeated `country=` makes the search page bail out to
 * the homepage, and a comma-separated value is read as one literal country name
 * and matches nothing. Multiple countries are therefore expressed with CT.gov's
 * expert AREA[] syntax in `term`, which does OR them correctly.
 *
 * Every value is quoted: names containing spaces or parentheses — 'Turkey
 * (Türkiye)' — otherwise break the query's own grammar.
 */
function _countryTerm(countries: readonly string[]): string {
  const quoted = countries.map((c) => `"${c}"`)
  return `AREA[LocationCountry](${quoted.join(' OR ')})`
}

/**
 * Build a ClinicalTrials.gov recruiting-search URL for the given condition and
 * countries. Empty/whitespace values are omitted rather than sent blank.
 *
 * `aggFilters` is appended unencoded so the URL matches the human-readable form
 * CT.gov itself produces (a colon is legal in a query string).
 */
export function buildTrialSearchUrl({ condition, countries }: TrialSearchInput): string {
  const params = new URLSearchParams()
  const cond = (condition ?? '').trim()
  const picked = (countries ?? []).map((c) => c.trim()).filter(Boolean)
  if (cond) params.set('cond', cond)
  if (picked.length > 0) params.set('term', _countryTerm(picked))

  const query = params.toString()
  const filter = `aggFilters=${RECRUITING_FILTER}`
  return `${CT_SEARCH_BASE}?${query ? `${query}&` : ''}${filter}`
}

/** Whether the user has given enough to make the search meaningful. */
export function canSearchTrials({ condition, countries }: TrialSearchInput): boolean {
  return Boolean(
    (condition ?? '').trim() ||
      (countries ?? []).some((c) => c.trim()),
  )
}
