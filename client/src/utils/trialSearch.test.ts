import { describe, it, expect } from 'vitest'
import {
  buildTrialSearchUrl,
  canSearchTrials,
  CT_SEARCH_BASE,
  RECRUITING_FILTER,
} from './trialSearch'

describe('buildTrialSearchUrl', () => {
  it('links to ClinicalTrials.gov filtered to recruiting trials', () => {
    const url = buildTrialSearchUrl({ condition: 'glioblastoma', location: 'Boston' })
    expect(url.startsWith(`${CT_SEARCH_BASE}?`)).toBe(true)
    // The recruiting filter is what makes this the *participation* search,
    // as opposed to the COMPLETED-only evidence search.
    expect(url).toContain(`aggFilters=${RECRUITING_FILTER}`)
  })

  it('passes condition and location as cond/locStr', () => {
    const url = buildTrialSearchUrl({ condition: 'glioblastoma', location: 'Boston' })
    const params = new URL(url).searchParams
    expect(params.get('cond')).toBe('glioblastoma')
    expect(params.get('locStr')).toBe('Boston')
  })

  it('encodes multi-word and special characters safely', () => {
    const url = buildTrialSearchUrl({
      condition: 'non-small cell lung cancer',
      location: 'Tel Aviv, Israel',
    })
    const params = new URL(url).searchParams
    expect(params.get('cond')).toBe('non-small cell lung cancer')
    expect(params.get('locStr')).toBe('Tel Aviv, Israel')
    // No raw spaces leak into the URL
    expect(url).not.toContain(' ')
  })

  it('omits an empty or whitespace-only condition', () => {
    const url = buildTrialSearchUrl({ condition: '   ', location: 'Berlin' })
    const params = new URL(url).searchParams
    expect(params.has('cond')).toBe(false)
    expect(params.get('locStr')).toBe('Berlin')
  })

  it('omits an empty location', () => {
    const url = buildTrialSearchUrl({ condition: 'melanoma' })
    const params = new URL(url).searchParams
    expect(params.get('cond')).toBe('melanoma')
    expect(params.has('locStr')).toBe(false)
  })

  it('trims surrounding whitespace', () => {
    const params = new URL(
      buildTrialSearchUrl({ condition: '  melanoma  ', location: '  Lyon  ' }),
    ).searchParams
    expect(params.get('cond')).toBe('melanoma')
    expect(params.get('locStr')).toBe('Lyon')
  })

  it('still produces a valid recruiting search when both fields are empty', () => {
    const url = buildTrialSearchUrl({})
    expect(url).toBe(`${CT_SEARCH_BASE}?aggFilters=${RECRUITING_FILTER}`)
  })

  it('keeps the filter colon unencoded, matching CT.gov\'s own URLs', () => {
    expect(buildTrialSearchUrl({ condition: 'x' })).toContain('aggFilters=status:rec')
  })
})

describe('canSearchTrials', () => {
  it('needs at least one of condition or location', () => {
    expect(canSearchTrials({ condition: 'melanoma' })).toBe(true)
    expect(canSearchTrials({ location: 'Paris' })).toBe(true)
    expect(canSearchTrials({ condition: 'melanoma', location: 'Paris' })).toBe(true)
  })

  it('rejects empty and whitespace-only input', () => {
    expect(canSearchTrials({})).toBe(false)
    expect(canSearchTrials({ condition: '', location: '' })).toBe(false)
    expect(canSearchTrials({ condition: '  ', location: '\t' })).toBe(false)
  })
})
