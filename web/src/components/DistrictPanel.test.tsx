/**
 * F5: the House panel keeps the Senate panel's F3 rules, one test per rule, against
 * fixtures/cases/house/house.json.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { NO_VOTES } from '../data/display'
import { parseHouse, type ParsedHouse } from '../data/parse'
import { DistrictPanel } from './DistrictPanel'

const raw = JSON.parse(readFileSync(resolve(__dirname, '../../fixtures/cases/house/house.json'), 'utf8'))
const house = parseHouse(raw)

function panel(key: string, data: ParsedHouse | null = house) {
  render(<DistrictPanel districtKey={key} house={data} onClose={() => {}} />)
  return screen.getByTestId('race-panel')
}

const EXACTLY_NO_VOTES = new RegExp(`^${NO_VOTES}$`)
const PROBABILITY_WORDS = /chance|probab|win/i

describe('DistrictPanel display rules', () => {
  it('names the district', () => {
    const el = panel('NC-01')
    expect(within(el).getByRole('heading', { level: 2 })).toHaveTextContent("NC-1North Carolina's 1st District, U.S. House")
  })

  it('modeled with votes: results plus a probability that says it is not a vote share', () => {
    const el = panel('NC-01')
    expect(within(el).getByTestId('results')).toHaveTextContent('88,123')
    const probs = within(el).getByTestId('probabilities')
    expect(probs).toHaveTextContent('62%')
    expect(probs).toHaveTextContent('not projected vote shares')
    expect(within(el).getByTestId('snapshot-time')).toHaveTextContent('North Carolina feed time 21:29 ET')
  })

  it('a settled probability reads >99%, not 100%', () => {
    expect(within(panel('SC-01')).getByTestId('probabilities')).toHaveTextContent('>99%')
  })

  it('non-modeled: votes, percentages and % reporting, and no probability field at all', () => {
    const el = panel('IL-01')
    const results = within(el).getByTestId('results')
    expect(results).toHaveTextContent('121,008')
    expect(results).toHaveTextContent('65.5%')
    expect(within(el).getByTestId('pct-reporting')).toHaveTextContent('71.0% reporting')
    expect(within(el).queryByTestId('probabilities')).toBeNull()
    expect(results.textContent).not.toMatch(PROBABILITY_WORDS)
    expect(el.textContent).not.toMatch(/\bwin|P\(/i)
  })

  it('non-modeled without a reporting figure says so instead of guessing', () => {
    expect(within(panel('IL-02')).getByTestId('pct-reporting')).toHaveTextContent('not published')
  })

  it('a probability on a race not marked modeled is refused', () => {
    const { modeled: _m, ...unmarked } = raw.races.find((r: { race: string }) => r.race === '2026-NC-H01')
    const data = parseHouse({ ...raw, races: [unmarked] })
    const el = panel('NC-01', data)
    expect(within(el).queryByTestId('probabilities')).toBeNull()
    expect(el.textContent).not.toContain('62%')
  })

  it('a modeled probability on zero votes is refused: that number would be pure prior', () => {
    const live = raw.races.find((r: { race: string }) => r.race === '2026-NC-H01')
    const data = parseHouse({ ...raw, races: [{ ...live, reported_votes: 0, votes: { D: 0, R: 0 }, vote_share: { D: 0, R: 0 } }] })
    const el = panel('NC-01', data)
    expect(within(el).getByTestId('no-votes')).toHaveTextContent(EXACTLY_NO_VOTES)
    expect(within(el).queryByTestId('probabilities')).toBeNull()
  })

  it('RCV with nulls (AK-AL): all four quantities named, none of them confident', () => {
    const el = panel('AK-AL')
    const probs = within(el).getByTestId('probabilities')
    for (const heading of ['Wins outright', 'Wins via RCV', 'Wins overall']) expect(probs).toHaveTextContent(heading)
    expect(within(el).getByTestId('p-no-rcv')).toHaveTextContent('Chance no ranked-choice count is needed: not yet estimated')
    expect(probs.textContent).not.toMatch(/\d+%/)
    expect(within(probs).getAllByLabelText('not yet estimated')).toHaveLength(6)
    expect(within(el).getByTestId('results')).toHaveTextContent('45,120')
  })

  it('RCV with estimates: all four quantities as published', () => {
    const probs = within(panel('ME-02')).getByTestId('probabilities')
    for (const value of ['42%', '12%', '54%', '73%']) expect(probs).toHaveTextContent(value)
  })

  it('waiting: exactly the no-votes text', () => {
    expect(within(panel('NC-02')).getByTestId('no-votes')).toHaveTextContent(EXACTLY_NO_VOTES)
  })

  it('live with a zero count: exactly the no-votes text', () => {
    expect(within(panel('OH-09')).getByTestId('no-votes')).toHaveTextContent(EXACTLY_NO_VOTES)
  })

  it('untracked and absent from house.json: Not tracked', () => {
    expect(within(panel('WY-AL')).getByTestId('not-tracked')).toHaveTextContent('Not tracked')
  })

  it('no house.json at all: exactly the no-votes text and no invented timestamp', () => {
    const el = panel('NC-01', null)
    expect(within(el).getByTestId('no-votes')).toHaveTextContent(EXACTLY_NO_VOTES)
    expect(within(el).queryByTestId('snapshot-time')).toBeNull()
  })

  it('an entry that fails the contract says the data is unavailable, not that nobody voted', () => {
    const el = panel('NC-01', parseHouse({ ...raw, races: [{ state: 'NC', race: '2026-NC-H01', status: 'live', p_win: 'oops' }] }))
    expect(el).toHaveTextContent('unavailable')
    expect(within(el).queryByTestId('no-votes')).toBeNull()
  })
})
