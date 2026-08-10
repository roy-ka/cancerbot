import { describe, it, expect } from 'vitest'
import type { Source } from '../types'
import {
  isTrialSource,
  prettifyPhase,
  prettifyStatus,
  trialBadgeSegments,
  trialBadgeLabel,
} from './trialBadge'

function source(overrides: Partial<Source> = {}): Source {
  return {
    id: 'nct:NCT01729260',
    url: 'https://clinicaltrials.gov/study/NCT01729260',
    text: '',
    name: 'A trial of X',
    source_type: 'clinicaltrials',
    ...overrides,
  }
}

describe('isTrialSource', () => {
  it('is true only for clinicaltrials sources', () => {
    expect(isTrialSource(source())).toBe(true)
    expect(isTrialSource(source({ source_type: 'pubmed' }))).toBe(false)
    expect(isTrialSource(source({ source_type: undefined }))).toBe(false)
  })
})

describe('prettifyPhase', () => {
  it('formats a single CT.gov phase', () => {
    expect(prettifyPhase('PHASE2')).toBe('Phase 2')
  })

  it('joins multiple phases with a slash', () => {
    expect(prettifyPhase('PHASE1, PHASE2')).toBe('Phase 1/2')
  })

  it('drops the meaningless NA phase', () => {
    expect(prettifyPhase('NA')).toBeNull()
    expect(prettifyPhase('na')).toBeNull()
  })

  it('title-cases non-numeric labels', () => {
    expect(prettifyPhase('EARLY_PHASE1')).toBe('Early Phase1')
  })

  it('returns null for empty/undefined', () => {
    expect(prettifyPhase(undefined)).toBeNull()
    expect(prettifyPhase(null)).toBeNull()
    expect(prettifyPhase('')).toBeNull()
  })
})

describe('prettifyStatus', () => {
  it('title-cases a simple status', () => {
    expect(prettifyStatus('COMPLETED')).toBe('Completed')
  })

  it('handles underscore-separated statuses', () => {
    expect(prettifyStatus('ACTIVE_NOT_RECRUITING')).toBe('Active Not Recruiting')
  })

  it('returns null for empty/undefined', () => {
    expect(prettifyStatus(undefined)).toBeNull()
    expect(prettifyStatus('')).toBeNull()
  })
})

describe('trialBadgeSegments / trialBadgeLabel', () => {
  it('leads with Trial and includes prettified phase + status', () => {
    const s = source({ phase: 'PHASE2', status: 'COMPLETED' })
    expect(trialBadgeSegments(s)).toEqual(['Trial', 'Phase 2', 'Completed'])
    expect(trialBadgeLabel(s)).toBe('Trial · Phase 2 · Completed')
  })

  it('omits phase when absent', () => {
    const s = source({ phase: null, status: 'COMPLETED' })
    expect(trialBadgeLabel(s)).toBe('Trial · Completed')
  })

  it('omits status when absent', () => {
    const s = source({ phase: 'PHASE3', status: null })
    expect(trialBadgeLabel(s)).toBe('Trial · Phase 3')
  })

  it('a bare registration still reads Trial', () => {
    expect(trialBadgeLabel(source({ phase: 'NA', status: undefined }))).toBe('Trial')
  })
})
