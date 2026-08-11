import { describe, it, expect } from 'vitest'
import {
  buildTrialSearchUrl,
  canSearchTrials,
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
