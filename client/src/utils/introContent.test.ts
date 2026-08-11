import { describe, it, expect } from 'vitest'
import {
  INTRO_TIPS,
  RAG_EXPLAINER,
  MIN_TIPS,
  MAX_TIPS,
  pickTips,
} from './introContent'

/** A deterministic rng cycling through the given values. */
function seq(values: number[]): () => number {
  let i = 0
  return () => values[i++ % values.length]
}

describe('INTRO_TIPS pool', () => {
  it('has around 20 prompts', () => {
    expect(INTRO_TIPS.length).toBeGreaterThanOrEqual(20)
  })

  it('has no empty or duplicate prompts', () => {
    expect(INTRO_TIPS.every((t) => t.trim().length > 0)).toBe(true)
    expect(new Set(INTRO_TIPS).size).toBe(INTRO_TIPS.length)
  })

  it('covers the requested topics', () => {
    expect(INTRO_TIPS.some((t) => /warburg/i.test(t))).toBe(true)
    expect(INTRO_TIPS.some((t) => /metabolic/i.test(t))).toBe(true)
    expect(INTRO_TIPS.some((t) => /clinical trial/i.test(t))).toBe(true)
  })
})

describe('RAG_EXPLAINER', () => {
  it('explains retrieval-augmented generation', () => {
    expect(RAG_EXPLAINER.toLowerCase()).toContain('retrieval-augmented generation')
    expect(RAG_EXPLAINER.length).toBeGreaterThan(50)
  })
})

describe('pickTips', () => {
  it('returns between MIN_TIPS and MAX_TIPS prompts', () => {
    for (let i = 0; i < 50; i++) {
      const n = pickTips().length
      expect(n).toBeGreaterThanOrEqual(MIN_TIPS)
      expect(n).toBeLessThanOrEqual(MAX_TIPS)
    }
  })

  it('never repeats a prompt within one pick', () => {
    for (let i = 0; i < 50; i++) {
      const tips = pickTips()
      expect(new Set(tips).size).toBe(tips.length)
    }
  })

  it('only returns prompts from the pool', () => {
    const pool = new Set(INTRO_TIPS)
    for (const tip of pickTips()) {
      expect(pool.has(tip)).toBe(true)
    }
  })

  it('is deterministic under an injected rng', () => {
    // rng() = 0 -> count = MIN_TIPS, and always takes index 0 of the shrinking pool
    const rng = seq([0])
    const chosen = pickTips(['a', 'b', 'c', 'd', 'e', 'f'], rng)
    expect(chosen).toEqual(['a', 'b', 'c', 'd'])
  })

  it('never returns more than the pool holds', () => {
    const chosen = pickTips(['only', 'two'], seq([0.99]))
    expect(chosen.length).toBe(2)
    expect(new Set(chosen).size).toBe(2)
  })
})
