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
 * location the user types are never sent to the CancerBot backend and never
 * stored — they go only to ClinicalTrials.gov, as a normal outbound link.
 */

export const CT_SEARCH_BASE = 'https://clinicaltrials.gov/search'

/** CT.gov's own filter token for "currently recruiting". */
export const RECRUITING_FILTER = 'status:rec'

export type TrialSearchInput = {
  condition?: string
  /** Coarse location — a city and/or country. Never GPS coordinates. */
  location?: string
}

/**
 * Build a ClinicalTrials.gov recruiting-search URL for the given condition and
 * coarse location. Empty/whitespace fields are omitted rather than sent blank.
 *
 * `aggFilters` is appended unencoded so the URL matches the human-readable form
 * CT.gov itself produces (a colon is legal in a query string).
 */
export function buildTrialSearchUrl({ condition, location }: TrialSearchInput): string {
  const params = new URLSearchParams()
  const cond = (condition ?? '').trim()
  const loc = (location ?? '').trim()
  if (cond) params.set('cond', cond)
  if (loc) params.set('locStr', loc)

  const query = params.toString()
  const filter = `aggFilters=${RECRUITING_FILTER}`
  return `${CT_SEARCH_BASE}?${query ? `${query}&` : ''}${filter}`
}

/** Whether the user has given enough to make the search meaningful. */
export function canSearchTrials({ condition, location }: TrialSearchInput): boolean {
  return Boolean((condition ?? '').trim() || (location ?? '').trim())
}
