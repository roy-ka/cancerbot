import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  buildTrialCountUrl,
  buildTrialSearchUrl,
  canSearchTrials,
  filterCountries,
  countRecruitingStudies,
  CT_API_STUDIES,
  CT_SEARCH_BASE,
  RECRUITING_FILTER,
} from './trialSearch'
import { TRIAL_COUNTRIES } from './trialCountries'

const term = (url: string) => new URL(url).searchParams.get('term')

describe('buildTrialSearchUrl', () => {
  it('links to ClinicalTrials.gov filtered to recruiting trials', () => {
    const url = buildTrialSearchUrl({ condition: 'glioblastoma', countries: ['Israel'] })
    expect(url.startsWith(`${CT_SEARCH_BASE}?`)).toBe(true)
    // The recruiting filter is what makes this the *participation* search,
    // as opposed to the COMPLETED-only evidence search.
    expect(url).toContain(`aggFilters=${RECRUITING_FILTER}`)
  })

  it('passes the condition as cond', () => {
    const url = buildTrialSearchUrl({ condition: 'glioblastoma', countries: ['Israel'] })
    expect(new URL(url).searchParams.get('cond')).toBe('glioblastoma')
  })

  it('expresses a single country with the AREA syntax', () => {
    const url = buildTrialSearchUrl({ condition: 'melanoma', countries: ['Israel'] })
    expect(term(url)).toBe('AREA[LocationCountry]("Israel")')
  })

  it('ORs multiple countries', () => {
    /* CT.gov's plain `country=` param takes one value only: a repeated
       `country=` bails the search page out to the homepage, and a
       comma-separated value is read as a single literal name. AREA[] is the
       only form that ORs correctly. */
    const url = buildTrialSearchUrl({ countries: ['Israel', 'Germany'] })
    expect(term(url)).toBe('AREA[LocationCountry]("Israel" OR "Germany")')
  })

  it('quotes names containing parentheses so they do not break the grammar', () => {
    const url = buildTrialSearchUrl({ countries: ['Turkey (Türkiye)', 'Israel'] })
    expect(term(url)).toBe('AREA[LocationCountry]("Turkey (Türkiye)" OR "Israel")')
  })

  it('never emits a bare country param, which cannot express multiples', () => {
    const url = buildTrialSearchUrl({ countries: ['Israel', 'Germany'] })
    const params = new URL(url).searchParams
    expect(params.has('country')).toBe(false)
    expect(params.has('locStr')).toBe(false)
    expect(params.getAll('term')).toHaveLength(1)
  })

  it('preserves the order the user picked', () => {
    const url = buildTrialSearchUrl({ countries: ['Germany', 'Israel'] })
    expect(term(url)).toBe('AREA[LocationCountry]("Germany" OR "Israel")')
  })

  it('omits the term when no country is selected', () => {
    const url = buildTrialSearchUrl({ condition: 'melanoma', countries: [] })
    const params = new URL(url).searchParams
    expect(params.has('term')).toBe(false)
    expect(params.get('cond')).toBe('melanoma')
  })

  it('drops blank entries rather than emitting empty quotes', () => {
    const url = buildTrialSearchUrl({ countries: ['  ', 'Israel', ''] })
    expect(term(url)).toBe('AREA[LocationCountry]("Israel")')
  })

  it('omits an empty or whitespace-only condition', () => {
    const url = buildTrialSearchUrl({ condition: '   ', countries: ['Israel'] })
    expect(new URL(url).searchParams.has('cond')).toBe(false)
  })

  it('encodes multi-word conditions safely', () => {
    const url = buildTrialSearchUrl({ condition: 'non-small cell lung cancer' })
    expect(new URL(url).searchParams.get('cond')).toBe('non-small cell lung cancer')
    expect(url).not.toContain(' ')
  })

  it('still produces a valid recruiting search when nothing is given', () => {
    expect(buildTrialSearchUrl({})).toBe(
      `${CT_SEARCH_BASE}?aggFilters=${RECRUITING_FILTER}`,
    )
  })

  it("keeps the filter colon unencoded, matching CT.gov's own URLs", () => {
    expect(buildTrialSearchUrl({ condition: 'x' })).toContain('aggFilters=status:rec')
  })
})

describe('city clause', () => {
  it('ANDs a city onto the country clause', () => {
    const url = buildTrialSearchUrl({ city: 'Tel Aviv', countries: ['Israel'] })
    expect(term(url)).toBe(
      'AREA[LocationCity]"Tel Aviv" AND AREA[LocationCountry]("Israel")',
    )
  })

  it('works with a city alone', () => {
    const url = buildTrialSearchUrl({ city: 'Boston' })
    expect(term(url)).toBe('AREA[LocationCity]"Boston"')
  })

  it('quotes the city, so multi-word names survive', () => {
    expect(term(buildTrialSearchUrl({ city: 'New York' }))).toContain('"New York"')
  })

  it('strips quotes and backslashes that would break out of the quoting', () => {
    // The city field is free text, so this is the one value a user can use to
    // inject query syntax; no real city name contains either character.
    const url = buildTrialSearchUrl({ city: 'Bos"ton\\', countries: ['Israel'] })
    expect(term(url)).toBe(
      'AREA[LocationCity]"Boston" AND AREA[LocationCountry]("Israel")',
    )
  })

  it('ignores a whitespace-only city', () => {
    const url = buildTrialSearchUrl({ city: '   ', countries: ['Israel'] })
    expect(term(url)).toBe('AREA[LocationCountry]("Israel")')
  })

  it('trims the city', () => {
    expect(term(buildTrialSearchUrl({ city: '  Lyon  ' }))).toBe(
      'AREA[LocationCity]"Lyon"',
    )
  })
})

describe('buildTrialCountUrl', () => {
  it('targets the public API and asks only for a count', () => {
    const url = buildTrialCountUrl({ city: 'Boston' })
    expect(url.startsWith(`${CT_API_STUDIES}?`)).toBe(true)
    const p = new URL(url).searchParams
    expect(p.get('countTotal')).toBe('true')
    // Only totalCount is read, so keep the body tiny
    expect(p.get('pageSize')).toBe('1')
    expect(p.get('fields')).toBe('LocationCity')
  })

  it('counts recruiting studies only, matching the deep link', () => {
    const p = new URL(buildTrialCountUrl({ city: 'Boston' })).searchParams
    expect(p.get('filter.overallStatus')).toBe('RECRUITING')
  })

  it('uses the same location term as the search link', () => {
    const input = { city: 'Tel Aviv', countries: ['Israel'] }
    const apiTerm = new URL(buildTrialCountUrl(input)).searchParams.get('query.term')
    expect(apiTerm).toBe(term(buildTrialSearchUrl(input)))
  })

  it('passes the condition as query.cond', () => {
    const p = new URL(
      buildTrialCountUrl({ condition: 'glioblastoma', city: 'Boston' }),
    ).searchParams
    expect(p.get('query.cond')).toBe('glioblastoma')
  })

  it('omits the term when there is no location', () => {
    const p = new URL(buildTrialCountUrl({ condition: 'melanoma' })).searchParams
    expect(p.has('query.term')).toBe(false)
  })
})

describe('countRecruitingStudies', () => {
  const okResponse = (body: unknown) =>
    ({ ok: true, json: async () => body }) as Response

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns the reported total', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okResponse({ totalCount: 340 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(countRecruitingStudies({ city: 'Tel Aviv' })).resolves.toBe(340)
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('returns zero as zero, distinct from a failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okResponse({ totalCount: 0 })))
    await expect(countRecruitingStudies({ city: 'Atlantis' })).resolves.toBe(0)
  })

  it('returns null on a network error, since that is not evidence of zero', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    await expect(countRecruitingStudies({ city: 'Boston' })).resolves.toBeNull()
  })

  it('returns null on a non-ok response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false } as Response))
    await expect(countRecruitingStudies({ city: 'Boston' })).resolves.toBeNull()
  })

  it('returns null when the payload has no usable total', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okResponse({ studies: [] })))
    await expect(countRecruitingStudies({ city: 'Boston' })).resolves.toBeNull()
  })

  it('passes the abort signal through', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okResponse({ totalCount: 1 }))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await countRecruitingStudies({ city: 'Boston' }, controller.signal)

    expect(fetchMock.mock.calls[0][1]).toEqual({ signal: controller.signal })
  })
})

describe('canSearchTrials', () => {
  it('needs at least a condition or a country', () => {
    expect(canSearchTrials({ condition: 'melanoma' })).toBe(true)
    expect(canSearchTrials({ countries: ['Israel'] })).toBe(true)
    expect(canSearchTrials({ condition: 'melanoma', countries: ['Israel'] })).toBe(true)
  })

  it('rejects empty and whitespace-only input', () => {
    expect(canSearchTrials({})).toBe(false)
    expect(canSearchTrials({ condition: '', countries: [] })).toBe(false)
    expect(canSearchTrials({ condition: '  ', countries: ['  '] })).toBe(false)
  })
})

describe('filterCountries', () => {
  it('puts the name that starts with the input first', () => {
    /* MUI's default substring filter matched anywhere, so typing 'is' offered
       Afghan-is-tan, Pak-is-tan and Taj-ik-is-tan before Israel. */
    const out = filterCountries(TRIAL_COUNTRIES, 'is')
    expect(out[0]).toBe('Israel')
  })

  it('drops matches that only occur mid-word', () => {
    const out = filterCountries(TRIAL_COUNTRIES, 'is')
    expect(out).not.toContain('Afghanistan')
    expect(out).not.toContain('Pakistan')
    expect(out).not.toContain('Tajikistan')
    expect(out).not.toContain('Guinea-Bissau')
  })

  it('still matches a later word, so "Islands" is reachable', () => {
    const out = filterCountries(TRIAL_COUNTRIES, 'is')
    expect(out).toContain('Aland Islands')
    // ...but only after the names that actually start with the input
    expect(out.indexOf('Israel')).toBeLessThan(out.indexOf('Aland Islands'))
  })

  it('is case-insensitive', () => {
    expect(filterCountries(TRIAL_COUNTRIES, 'ISRAEL')[0]).toBe('Israel')
    expect(filterCountries(TRIAL_COUNTRIES, 'israel')[0]).toBe('Israel')
  })

  it('ignores accents, so the ASCII spelling finds the real name', () => {
    // CT.gov's own spellings carry diacritics that users will not type
    expect(filterCountries(TRIAL_COUNTRIES, 'turkiye')).toContain('Turkey (Türkiye)')
    expect(filterCountries(TRIAL_COUNTRIES, 'cote')).toContain('Côte d’Ivoire')
  })

  it('reaches a word inside parentheses', () => {
    expect(filterCountries(TRIAL_COUNTRIES, 'turk')).toContain('Turkey (Türkiye)')
  })

  it('returns everything for empty or whitespace input', () => {
    expect(filterCountries(TRIAL_COUNTRIES, '')).toHaveLength(TRIAL_COUNTRIES.length)
    expect(filterCountries(TRIAL_COUNTRIES, '   ')).toHaveLength(TRIAL_COUNTRIES.length)
  })

  it('returns nothing for a country CT.gov does not list', () => {
    expect(filterCountries(TRIAL_COUNTRIES, 'Atlantis')).toEqual([])
  })

  it('never invents an option that is not in the list', () => {
    const pool = new Set(TRIAL_COUNTRIES)
    for (const match of filterCountries(TRIAL_COUNTRIES, 'a')) {
      expect(pool.has(match)).toBe(true)
    }
  })
})

describe('TRIAL_COUNTRIES', () => {
  it('holds the full CT.gov country list', () => {
    expect(TRIAL_COUNTRIES.length).toBe(226)
  })

  it('has no duplicates or blanks', () => {
    expect(new Set(TRIAL_COUNTRIES).size).toBe(TRIAL_COUNTRIES.length)
    expect(TRIAL_COUNTRIES.every((c) => c.trim() === c && c.length > 0)).toBe(true)
  })

  it('is sorted, so the dropdown is scannable', () => {
    expect([...TRIAL_COUNTRIES]).toEqual([...TRIAL_COUNTRIES].sort())
  })

  it("keeps CT.gov's exact spelling, which the AREA query matches on", () => {
    // Tidying this to "Turkey" would silently match nothing
    expect(TRIAL_COUNTRIES).toContain('Turkey (Türkiye)')
    expect(TRIAL_COUNTRIES).toContain('United States')
  })

  it('contains no quote or backslash that would break the AREA query', () => {
    expect(TRIAL_COUNTRIES.some((c) => c.includes('"') || c.includes('\\'))).toBe(false)
  })
})
