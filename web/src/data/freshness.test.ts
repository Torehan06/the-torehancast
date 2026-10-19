import { describe, expect, it } from 'vitest'
import { formatAge, freshness } from './freshness'

const t0 = new Date('2026-11-04T02:30:00Z')
const at = (s: number) => new Date(t0.getTime() + s * 1000)

describe('freshness (F4)', () => {
  it('is loading before any data, unavailable if the first fetch fails', () => {
    expect(freshness({ generatedAt: null, lastError: null, now: t0, staleAfterS: 120 })).toEqual({ kind: 'loading' })
    expect(freshness({ generatedAt: null, lastError: 'HTTP 500', now: t0, staleAfterS: 120 })).toEqual({
      kind: 'unavailable',
      error: 'HTTP 500',
    })
  })

  it('turns stale strictly after the threshold', () => {
    expect(freshness({ generatedAt: t0, lastError: null, now: at(120), staleAfterS: 120 }).kind).toBe('fresh')
    expect(freshness({ generatedAt: t0, lastError: null, now: at(121), staleAfterS: 120 })).toEqual({
      kind: 'stale',
      ageS: 121,
    })
  })

  it('reports a failing fetch even when the data is recent, with its age', () => {
    expect(freshness({ generatedAt: t0, lastError: 'timed out', now: at(30), staleAfterS: 120 })).toEqual({
      kind: 'failing',
      ageS: 30,
      error: 'timed out',
    })
  })

  it('clamps a negative age from a slow visitor clock to zero', () => {
    expect(freshness({ generatedAt: at(50), lastError: null, now: t0, staleAfterS: 120 })).toEqual({ kind: 'fresh', ageS: 0 })
  })

  it('formats ages', () => {
    expect(formatAge(42)).toBe('42s')
    expect(formatAge(185)).toBe('3 min 5s')
    expect(formatAge(3720)).toBe('1 h 2 min')
  })
})
