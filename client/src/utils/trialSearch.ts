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

/** CT.gov's public REST API. Sends `access-control-allow-origin: *`, so the
 *  browser can query it directly — no backend route, and the user's condition
 *  and location still never reach the CancerBot server. */
export const CT_API_STUDIES = 'https://clinicaltrials.gov/api/v2/studies'

export type TrialSearchInput = {
  condition?: string
  /**
   * Coarse locations — country names, which must match CT.gov's own spelling
   * (see TRIAL_COUNTRIES). Never GPS coordinates.
   */
  countries?: readonly string[]
  /** Optional city, free text: CT.gov has no city list or typeahead to pick from. */
  city?: string
}

/**
 * Quote a value for CT.gov's AREA[] grammar.
 *
 * Quoting is required because values contain spaces and parentheses — 'Turkey
 * (Türkiye)', 'Tel Aviv' — which would otherwise be parsed as query syntax. A
 * double quote or backslash inside the value would break out of the quoting, so
 * they are dropped: the city field is free text, and no legitimate city name
 * contains either.
 */
function _quote(value: string): string {
  return `"${value.replace(/["\\]/g, '')}"`
}

/**
 * Build the location clause from a city and/or a set of countries.
 *
 * CT.gov's plain `country=` parameter takes a single value only — verified
 * against the live site, a repeated `country=` makes the search page bail out to
 * the homepage, and a comma-separated value is read as one literal country name
 * and matches nothing. The expert AREA[] syntax in `term` is the only form that
 * ORs countries, and it is also what lets a city be ANDed onto them.
 *
 * Returns null when there is no location to express.
 */
function _locationTerm({ countries, city }: TrialSearchInput): string | null {
  const clauses: string[] = []
  const town = (city ?? '').trim()
  const picked = (countries ?? []).map((c) => c.trim()).filter(Boolean)

  if (town) clauses.push(`AREA[LocationCity]${_quote(town)}`)
  if (picked.length > 0) {
    clauses.push(`AREA[LocationCountry](${picked.map(_quote).join(' OR ')})`)
  }
  return clauses.length > 0 ? clauses.join(' AND ') : null
}

/**
 * Build a ClinicalTrials.gov recruiting-search URL for the given condition and
 * location. Empty/whitespace values are omitted rather than sent blank.
 *
 * `aggFilters` is appended unencoded so the URL matches the human-readable form
 * CT.gov itself produces (a colon is legal in a query string).
 */
export function buildTrialSearchUrl(input: TrialSearchInput): string {
  const params = new URLSearchParams()
  const cond = (input.condition ?? '').trim()
  const location = _locationTerm(input)
  if (cond) params.set('cond', cond)
  if (location) params.set('term', location)

  const query = params.toString()
  const filter = `aggFilters=${RECRUITING_FILTER}`
  return `${CT_SEARCH_BASE}?${query ? `${query}&` : ''}${filter}`
}

/**
 * Build the API URL that counts how many recruiting studies match.
 *
 * Kept separate from buildTrialSearchUrl (which targets the human search page)
 * and pure, so the query shape is testable without a network call. `pageSize=1`
 * plus a single field keeps the response tiny — only `totalCount` is used.
 */
export function buildTrialCountUrl(input: TrialSearchInput): string {
  const params = new URLSearchParams()
  const cond = (input.condition ?? '').trim()
  const location = _locationTerm(input)
  if (cond) params.set('query.cond', cond)
  if (location) params.set('query.term', location)
  params.set('filter.overallStatus', 'RECRUITING')
  params.set('countTotal', 'true')
  params.set('pageSize', '1')
  params.set('fields', 'LocationCity')
  return `${CT_API_STUDIES}?${params.toString()}`
}

/**
 * Ask CT.gov how many recruiting studies match, so a mistyped or unknown city
 * is visible before the user leaves the app.
 *
 * This exists instead of a typeahead because CT.gov cannot offer one: its
 * location search matches whole terms only (`boston` → 2687 studies, `bosto` →
 * 0, and wildcards do not help), its suggest endpoint has no city dictionary,
 * and the stats endpoint caps at the top 250 of ~56,000 cities. So the city is
 * free text, and this call reports what CT.gov actually has for it.
 *
 * Returns null if the request fails or is aborted — the caller treats that as
 * "unknown" rather than "none", since a network error is not evidence of zero.
 */
export async function countRecruitingStudies(
  input: TrialSearchInput,
  signal?: AbortSignal,
): Promise<number | null> {
  try {
    const res = await fetch(buildTrialCountUrl(input), { signal })
    if (!res.ok) return null
    const data = await res.json()
    return typeof data?.totalCount === 'number' ? data.totalCount : null
  } catch {
    return null
  }
}

/** Lowercase and strip accents, so 'Türkiye' is reachable by typing 'turkiye'. */
function _fold(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
}

/**
 * Filter the country list for the dropdown.
 *
 * MUI's default filter matches a substring anywhere, which is unusable on this
 * list: typing 'is' offers Afghan-is-tan, Pak-is-tan, Guinea-B-is-sau and
 * Taj-ik-is-tan, burying Israel. People type the *start* of a name, so matches
 * are anchored — first names starting with the input, then names with any word
 * starting with it ('Islands'), and nothing else.
 *
 * Lives here rather than in trialCountries.ts because that file is generated
 * data and gets overwritten when the list is refreshed.
 */
export function filterCountries(
  options: readonly string[],
  input: string,
): string[] {
  const query = _fold(input.trim())
  if (!query) return [...options]

  const startsWithName: string[] = []
  const startsWithWord: string[] = []
  for (const option of options) {
    const folded = _fold(option)
    if (folded.startsWith(query)) {
      startsWithName.push(option)
    } else if (
      // Split on anything non-alphanumeric so parenthesised and apostrophised
      // names — 'Turkey (Türkiye)', 'Côte d’Ivoire' — are reachable by any word.
      folded.split(/[^a-z0-9]+/).some((word) => word && word.startsWith(query))
    ) {
      startsWithWord.push(option)
    }
  }
  return [...startsWithName, ...startsWithWord]
}

/** Whether the user has given enough to make the search meaningful. */
export function canSearchTrials({ condition, countries, city }: TrialSearchInput): boolean {
  return Boolean(
    (condition ?? '').trim() ||
      (city ?? '').trim() ||
      (countries ?? []).some((c) => c.trim()),
  )
}
