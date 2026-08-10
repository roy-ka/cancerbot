import type { Source } from '../types'

/**
 * Pure helpers for the clinical-trial source badge.
 *
 * Clinical-trial sources (source_type === 'clinicaltrials', `nct:` ids) render
 * with a distinct "Trial · Phase · Status" badge so users can tell trial
 * registrations apart from published literature. The backend surfaces `phase`
 * and `status` by parsing the trial's own full_text (see
 * src/db/repositories/messeges.py:_parse_trial_facts); the raw values arrive in
 * ClinicalTrials.gov form (e.g. "PHASE2", "COMPLETED"), which we prettify here.
 */

export function isTrialSource(source: Source): boolean {
  return source.source_type === 'clinicaltrials'
}

/** "PHASE2" -> "Phase 2", "PHASE1, PHASE2" -> "Phase 1/2", "NA" -> null. */
export function prettifyPhase(phase?: string | null): string | null {
  if (!phase) return null
  const nums = phase
    .split(',')
    .map((p) => p.trim().toUpperCase())
    .map((p) => p.match(/^PHASE\s*([0-4]+)$/)?.[1])
    .filter((n): n is string => Boolean(n))
  if (nums.length > 0) return `Phase ${nums.join('/')}`
  // "EARLY_PHASE1" and other non-numeric labels: title-case them, drop "NA".
  const cleaned = phase.trim()
  if (!cleaned || cleaned.toUpperCase() === 'NA') return null
  return cleaned
    .split(/[_\s]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ')
}

/** "COMPLETED" -> "Completed", "ACTIVE_NOT_RECRUITING" -> "Active Not Recruiting". */
export function prettifyStatus(status?: string | null): string | null {
  if (!status) return null
  const cleaned = status.trim()
  if (!cleaned) return null
  return cleaned
    .split(/[_\s]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ')
}

/**
 * Badge label segments for a trial source, e.g. ["Trial", "Phase 2",
 * "Completed"]. Always leads with "Trial"; phase/status segments are omitted
 * when absent so a bare registration still reads "Trial".
 */
export function trialBadgeSegments(source: Source): string[] {
  const segments = ['Trial']
  const phase = prettifyPhase(source.phase)
  if (phase) segments.push(phase)
  const status = prettifyStatus(source.status)
  if (status) segments.push(status)
  return segments
}

export function trialBadgeLabel(source: Source): string {
  return trialBadgeSegments(source).join(' · ')
}
