import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { leader, party } from './display'
import { pollForView } from './freshness'
import { parseHouse } from './parse'

const raw = JSON.parse(readFileSync(resolve(__dirname, '../../fixtures/cases/house/house.json'), 'utf8'))

describe('parseHouse', () => {
  it('keys races by race ID, so two districts of one state stay apart', () => {
    const house = parseHouse(raw)
    expect(house.invalid).toEqual([])
    expect(house.races.size).toBe(raw.races.length)
    expect(house.races.get('2026-NC-H01')?.status).toBe('live')
    expect(house.races.get('2026-NC-H02')?.status).toBe('waiting')
  })

  it('one bad entry costs only that race', () => {
    const house = parseHouse({ ...raw, races: [...raw.races, { state: 'NC', race: '2026-NC-H03', status: 'live', p_win: 'oops' }, { nope: 1 }] })
    expect(house.invalid).toEqual(['2026-NC-H03', '??'])
    expect(house.races.size).toBe(raw.races.length)
  })

  it('throws on a broken envelope so the poller reports a failed fetch', () => {
    expect(() => parseHouse({ races: [] })).toThrow()
    expect(() => parseHouse({ generated_at: raw.generated_at, mode: 'live', states: [] })).toThrow()
  })
})

describe('tile colour', () => {
  const house = parseHouse(raw)

  it('a second candidate of a party keeps the party colour', () => {
    expect(party('D2')).toBe('D')
    expect(party('R3')).toBe('R')
    expect(party('other')).toBe('other')
    expect(party('I')).toBe('other')
    expect(leader(house.races.get('2026-CA-H12'))).toMatchObject({ key: 'D2', basis: 'vote_share', strength: 'light' })
  })

  it('a count lead in a results-only race never looks like a forecast', () => {
    expect(leader(house.races.get('2026-IL-H01'))).toMatchObject({ key: 'D', basis: 'vote_share', strength: 'light' })
  })

  it('an RCV race with null probabilities falls back to its count lead', () => {
    expect(leader(house.races.get('2026-AK-HAL'))).toMatchObject({ key: 'R', basis: 'vote_share', strength: 'light' })
  })

  it('no leader for a tie, a zero-vote count, or a race absent from the file', () => {
    expect(leader(house.races.get('2026-TX-H01'))).toBeNull()
    expect(leader(house.races.get('2026-OH-H09'))).toBeNull()
    expect(leader(house.races.get('2026-WY-HAL'))).toBeNull()
  })
})

describe('which poll speaks for the banner', () => {
  interface Poll { data: unknown; lastError: string | null; settled: boolean; name: string }
  const summary: Poll = { data: {}, lastError: null, settled: true, name: 'summary' }
  const missing: Poll = { data: null, lastError: null, settled: true, name: 'house' }

  it('the Senate view always reads summary.json', () => {
    expect(pollForView('senate', summary, { ...missing, data: {} }).name).toBe('summary')
  })

  it('a missing house.json leaves the banner to summary.json', () => {
    expect(pollForView('house', summary, missing).name).toBe('summary')
  })

  it('a snapshot kept from an earlier visit waits for its first refresh', () => {
    expect(pollForView('house', summary, { ...missing, data: {}, settled: false }).name).toBe('summary')
  })

  it('house.json answers for itself once it exists or fails', () => {
    expect(pollForView('house', summary, { ...missing, data: {} }).name).toBe('house')
    expect(pollForView('house', summary, { ...missing, lastError: 'HTTP 500' }).name).toBe('house')
  })
})
