import { readdirSync, readFileSync, statSync } from 'node:fs'
import { basename, join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { parseSummary, validatePublicFile } from './parse'

const ROOT = resolve(__dirname, '../../fixtures')

function jsonFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    return statSync(path).isDirectory() ? jsonFiles(path) : name.endsWith('.json') ? [path] : []
  })
}

const files = jsonFiles(ROOT)

describe('every fixture matches the strict contract (F1)', () => {
  it('has fixtures to check', () => {
    expect(files.length).toBeGreaterThan(60)
  })

  it.each(files.map((f) => [f.slice(ROOT.length + 1), f]))('%s', (_rel, path) => {
    const raw = JSON.parse(readFileSync(path, 'utf8'))
    expect(validatePublicFile(basename(path), raw)).toEqual([])
    if (basename(path) === 'summary.json') {
      const parsed = parseSummary(raw)
      expect(parsed.invalid).toEqual([])
      expect(parsed.races.size).toBe(raw.states.length)
    }
  })

  it('contract-v1 fixtures carry the M3 fields', () => {
    // rcv-null's Alaska has no counts on purpose.
    const preM3 = (f: string) => f.includes('/rcv-null/')
    for (const path of files.filter((f) => !preM3(f))) {
      const raw = JSON.parse(readFileSync(path, 'utf8'))
      expect(validatePublicFile(basename(path), raw, true), path).toEqual([])
    }
  })
})

describe('strict validation catches drift', () => {
  const name = '2026-GA-SEN.json'
  const live = JSON.parse(readFileSync(join(ROOT, 'cases/partial-modeled/races', name), 'utf8'))

  it('rejects a renamed field', () => {
    const { p_win, ...rest } = live
    expect(validatePublicFile(name, { ...rest, win_prob: p_win }).length).toBeGreaterThan(0)
  })

  it('rejects a probability outside [0, 1]', () => {
    expect(validatePublicFile(name, { ...live, p_win: { D: 1.2, R: -0.2 } }).length).toBeGreaterThan(0)
  })

  it('flags a payload without the M3 fields only when v1 is required', () => {
    const { modeled: _m, votes: _v, vote_share: _s, pct_reporting: _p, ...legacy } = live
    expect(validatePublicFile(name, legacy)).toEqual([])
    expect(validatePublicFile(name, legacy, true)).toEqual([
      `${name}: GA: missing "modeled" (M3)`,
      `${name}: GA: missing "votes" (M3)`,
    ])
  })

  it('requires race identity (v2) in strict mode only', () => {
    const { race_type: _t, district: _d, ...v1 } = live
    expect(validatePublicFile(name, v1).length).toBeGreaterThan(0)
    expect(validatePublicFile(name, { ...live, race: 'US Senate' }).length).toBeGreaterThan(0)
    const summary = { generated_at: '2026-11-03T20:00:00Z', mode: 'live', states: [v1] }
    expect(parseSummary(summary).invalid).toEqual([])
  })

  it('validates house.json', () => {
    const house = { generated_at: '2026-11-03T20:00:00Z', mode: 'live', races: [
      { ...live, state: 'NC', race: '2026-NC-H01', race_type: 'house', district: 1 },
    ] }
    expect(validatePublicFile('house.json', house, true)).toEqual([])
  })

  it('rejects unknown file names, including v1 per-state detail files', () => {
    expect(validatePublicFile('priors.json', {})).toEqual(['priors.json: not a recognised public file name'])
    expect(validatePublicFile('GA.json', live)).toEqual(['GA.json: not a recognised public file name'])
  })
})

describe('runtime parsing is forgiving per race', () => {
  it('keeps good races when one entry is malformed', () => {
    const raw = JSON.parse(readFileSync(join(ROOT, 'demo/summary.json'), 'utf8'))
    raw.states.push({ state: 'IA', status: 'live', p_win: 'oops' })
    raw.states.push({ state: 'GA', race: 'x', as_of: null, status: 'waiting', extra: 1 })
    const parsed = parseSummary(raw)
    expect(parsed.invalid).toEqual(['IA'])
    expect(parsed.races.get('GA')?.status).toBe('waiting') // later entry wins; extra field ignored
  })

  it('throws on a broken envelope so the poller reports a failed fetch', () => {
    expect(() => parseSummary({ states: [] })).toThrow()
    expect(() => parseSummary('<html>')).toThrow()
  })
})
