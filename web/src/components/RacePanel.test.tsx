/**
 * F3: the five fixture cases from PLAN.md, each asserted against a saved fixture
 * under fixtures/cases/.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { NO_VOTES } from '../data/display'
import { parseSummary } from '../data/parse'
import { SENATE_RACES_2026 } from '../data/states'
import { RacePanel } from './RacePanel'

function load(name: string) {
  const path = resolve(__dirname, '../../fixtures/cases', name, 'summary.json')
  return parseSummary(JSON.parse(readFileSync(path, 'utf8')))
}

function panel(name: string, code: string) {
  render(<RacePanel code={code} summary={load(name)} onClose={() => {}} />)
  return screen.getByTestId('race-panel')
}

const PROBABILITY_WORDS = /chance|probab|win/i

describe('RacePanel fixture cases', () => {
  it('waiting: every Senate race shows exactly the no-votes text and a timestamp', () => {
    const summary = load('waiting')
    for (const { state } of SENATE_RACES_2026) {
      const { unmount } = render(<RacePanel code={state.code} summary={summary} onClose={() => {}} />)
      expect(screen.getByTestId('no-votes')).toHaveTextContent(new RegExp(`^${NO_VOTES}$`))
      expect(screen.queryByTestId('probabilities')).toBeNull()
      expect(screen.getByTestId('snapshot-time')).toBeInTheDocument()
      unmount()
    }
  })

  it('partial non-modeled: names, counts, shares and % reporting, and no probability element at all', () => {
    const el = panel('partial-nonmodeled', 'IL')
    const results = within(el).getByTestId('results')
    expect(results).toHaveTextContent('IL Fixture A (Dem)')
    expect(results).toHaveTextContent('801,233')
    expect(results).toHaveTextContent('57.1%')
    expect(within(el).getByTestId('pct-reporting')).toHaveTextContent('42.0% reporting')
    expect(within(el).queryByTestId('probabilities')).toBeNull()
    expect(within(el).getByTestId('no-forecast')).toHaveTextContent('no forecast')
    expect(within(el).getByTestId('results').textContent).not.toMatch(PROBABILITY_WORDS)
  })

  it('partial non-modeled without a reporting figure says so instead of guessing', () => {
    const el = panel('partial-nonmodeled', 'VA')
    expect(within(el).getByTestId('pct-reporting')).toHaveTextContent('not published')
  })

  it('partial modeled: results plus a probability that says it is not a vote share', () => {
    const el = panel('partial-modeled', 'GA')
    expect(within(el).getByTestId('results')).toHaveTextContent('1,210,455')
    const probs = within(el).getByTestId('probabilities')
    expect(probs).toHaveTextContent('Chance of winning')
    expect(probs).toHaveTextContent('87%')
    expect(probs).toHaveTextContent('not projected vote shares')
    expect(within(el).getByTestId('margin')).toHaveTextContent('D+1.7')
    expect(within(el).getByTestId('snapshot-time')).toHaveTextContent('feed time 21:29 ET')
  })

  it('RCV with null probabilities: all four quantities shown, none of them confident', () => {
    for (const code of ['ME', 'AK']) {
      const { unmount } = render(<RacePanel code={code} summary={load('rcv-null')} onClose={() => {}} />)
      const probs = screen.getByTestId('probabilities')
      for (const heading of ['Wins outright', 'Wins via RCV', 'Wins overall']) expect(probs).toHaveTextContent(heading)
      expect(screen.getByTestId('p-no-rcv')).toHaveTextContent('Chance no ranked-choice count is needed: not yet estimated')
      expect(probs.textContent).not.toMatch(/\d+%/) // no number anywhere in the forecast block
      expect(within(probs).getAllByLabelText('not yet estimated')).toHaveLength(9)
      unmount()
    }
  })

  it('RCV without vote counts does not claim "no votes"', () => {
    const el = panel('rcv-null', 'AK')
    expect(within(el).queryByTestId('no-votes')).toBeNull()
  })

  it('final: complete counts and the settled probability shown as >99%, not 100%', () => {
    const el = panel('final', 'GA')
    expect(within(el).getByTestId('pct-reporting')).toHaveTextContent('100.0% reporting')
    expect(within(el).getByTestId('probabilities')).toHaveTextContent('>99%')
    expect(within(el).getByTestId('probabilities').textContent).not.toContain('100%')
  })

  it('a race absent from the JSON shows the no-votes text', () => {
    const el = panel('final', 'TX')
    expect(within(el).getByTestId('no-votes')).toHaveTextContent(NO_VOTES)
  })

  it('pre-M3 replay output (no modeled flag) shows no probability', () => {
    const path = resolve(__dirname, '../../fixtures/replay-ga/summary.json')
    const summary = parseSummary(JSON.parse(readFileSync(path, 'utf8')))
    render(<RacePanel code="GA" summary={summary} onClose={() => {}} />)
    expect(screen.queryByTestId('probabilities')).toBeNull()
    expect(screen.getByTestId('results')).toHaveTextContent('Raphael Warnock')
  })
})
