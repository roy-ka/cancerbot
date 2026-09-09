import { describe, it, expect } from 'vitest'
import {
  GUIDE_AREAS,
  GUIDE_ENTRIES,
  entriesForArea,
  type GuideArea,
} from './iconGuide'

describe('GUIDE_ENTRIES', () => {
  it('has a unique key per entry', () => {
    const keys = GUIDE_ENTRIES.map((e) => e.key)
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('gives every entry a label and a description', () => {
    for (const entry of GUIDE_ENTRIES) {
      expect(entry.label.trim().length, `${entry.key} label`).toBeGreaterThan(0)
      expect(entry.description.trim().length, `${entry.key} description`).toBeGreaterThan(0)
    }
  })

  it('keeps each description to a short brief', () => {
    for (const entry of GUIDE_ENTRIES) {
      expect(entry.description.length, `${entry.key} is too long`).toBeLessThanOrEqual(110)
    }
  })

  it('assigns every entry to a known area', () => {
    for (const entry of GUIDE_ENTRIES) {
      expect(GUIDE_AREAS).toContain(entry.area)
    }
  })

  it('covers the icons a user actually sees on the chat page', () => {
    const keys = GUIDE_ENTRIES.map((e) => e.key)
    for (const expected of [
      'account',
      'healthProfile',
      'changeEmail',
      'findTrials',
      'privacy',
      'about',
      'guide',
      'feedback',
      'deleteConversation',
      'translate',
      'trialBadge',
      'citation',
      'send',
    ] as const) {
      expect(keys).toContain(expected)
    }
  })

  it('does not document the ninja-only view', () => {
    const text = JSON.stringify(GUIDE_ENTRIES).toLowerCase()
    expect(text).not.toContain('ninja')
  })

  it('marks the sidebar toggles as small-screen only', () => {
    const byKey = Object.fromEntries(GUIDE_ENTRIES.map((e) => [e.key, e]))
    expect(byKey.toggleSidebar.smallScreenOnly).toBe(true)
    expect(byKey.closeSidebar.smallScreenOnly).toBe(true)
  })

  it('gives emoji entries the same glyph the UI renders', () => {
    const byKey = Object.fromEntries(GUIDE_ENTRIES.map((e) => [e.key, e]))
    expect(byKey.send.emoji).toBe('🦀')
    expect(byKey.toggleSidebar.emoji).toBe('☰')
    expect(byKey.closeSidebar.emoji).toBe('✕')
  })
})

describe('entriesForArea', () => {
  it('partitions all entries across the areas with none lost', () => {
    const total = GUIDE_AREAS.reduce((n, area) => n + entriesForArea(area).length, 0)
    expect(total).toBe(GUIDE_ENTRIES.length)
  })

  it('returns only entries from the requested area', () => {
    for (const area of GUIDE_AREAS) {
      for (const entry of entriesForArea(area)) {
        expect(entry.area).toBe(area)
      }
    }
  })

  it('leaves no area empty', () => {
    for (const area of GUIDE_AREAS) {
      expect(entriesForArea(area).length, `${area} is empty`).toBeGreaterThan(0)
    }
  })

  it('returns nothing for an unknown area', () => {
    expect(entriesForArea('Nope' as GuideArea)).toEqual([])
  })
})
