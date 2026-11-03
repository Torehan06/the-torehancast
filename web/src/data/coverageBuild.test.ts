import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { stringify } from 'yaml'
import { readCoverage } from '../../scripts/coverage'

describe('build-only coverage reader', () => {
  it('follows config changes, source status and district subsets, emitting IDs only', () => {
    const root = mkdtempSync(join(tmpdir(), 'coverage-'))
    const write = (file: string, value: unknown) => writeFileSync(join(root, file), stringify(value))
    try {
      mkdirSync(join(root, 'results'))
      write('races.yaml', { races: { '2026-GA-SEN': { status: 'done', ranked_choice: false }, '2026-GA-H01': { status: 'done', ranked_choice: false }, '2026-GA-H02': { status: 'dropped', ranked_choice: false } } })
      write('feeds.yaml', { feeds: { '2026-GA-SEN': { status: 'ready', adapter: 'ga', url: 'SOURCE_CANARY', notes: 'NOTES_CANARY' }, '2026-GA-H01': { status: 'ready', adapter: 'ga', url: 'SOURCE_CANARY' }, '2026-GA-H02': { status: 'dropped', adapter: 'ga', url: 'SOURCE_CANARY' } } })
      write('results/GA.yaml', { results: { sources: { existing: { same_as: '2026-GA-SEN', status: 'ready', contests: [{ office: 'house', districts: 'all' }] } } } })
      write('results/VT.yaml', { results: { sources: { new_source: { status: 'ready', adapter: 'new', url: 'SOURCE_CANARY', contests: [{ office: 'house', districts: [1] }] } } } })
      write('results/CA.yaml', { results: { sources: { unavailable: { status: 'dropped', contests: [{ office: 'house', districts: 'all' }] } } } })
      const coverage = readCoverage(root)
      expect(coverage.trackedRaceIds).toHaveLength(16) // GA Senate + all 14 House + VT-AL
      expect(coverage.trackedRaceIds).toContain('2026-VT-HAL')
      expect(coverage.trackedRaceIds).toContain('2026-GA-H02') // dropped forecast, ready results-only source
      expect(JSON.stringify(coverage)).not.toMatch(/CANARY|adapter|notes|url/)
      expect(coverage.rankedChoiceRaceIds).toEqual([])
      write('results/VT.yaml', { results: { sources: {} } })
      expect(readCoverage(root).trackedRaceIds).not.toContain('2026-VT-HAL')
    } finally { rmSync(root, { recursive: true, force: true }) }
  })
})
