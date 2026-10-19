import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { parseSummary } from '../data/parse'
import { SwingSeats } from './SwingSeats'

function load(name: string) {
  const path = resolve(__dirname, '../../fixtures', name, 'summary.json')
  return parseSummary(JSON.parse(readFileSync(path, 'utf8')))
}

function tile(code: string) {
  return document.querySelector(`[data-race="${code}"]`)!
}

describe('SwingSeats', () => {
  it('shows all 13 forecast seats', () => {
    render(<SwingSeats summary={load('cases/waiting')} selected={null} onSelect={() => {}} />)
    expect(document.querySelectorAll('.race-item--swing')).toHaveLength(13)
    expect(screen.queryByTestId(/swing-prob-/)).toBeNull()
  })

  it('leads with the favourite’s win probability in its party colour', () => {
    render(<SwingSeats summary={load('demo')} selected={null} onSelect={() => {}} />)
    expect(screen.getByTestId('swing-prob-GA')).toHaveTextContent('87%')
    expect(tile('GA')).toHaveClass('lead-D')
    expect(screen.getByTestId('swing-prob-NC')).toHaveTextContent('68%')
    expect(tile('NC')).toHaveClass('lead-R')
    expect(tile('GA')).toHaveTextContent('GA Fixture A (Dem) to win')
  })

  it('never puts a vote share in the big-number slot', () => {
    render(<SwingSeats summary={load('demo')} selected={null} onSelect={() => {}} />)
    // Maine's RCV probabilities are null; it leads only on first-choice votes.
    expect(screen.queryByTestId('swing-prob-ME')).toBeNull()
    expect(tile('ME')).toHaveTextContent('leads with 45.2% of the vote')
  })

  it('shows no probability for pre-M3 data without the modeled flag', () => {
    render(<SwingSeats summary={load('replay-ga')} selected={null} onSelect={() => {}} />)
    expect(screen.queryByTestId('swing-prob-GA')).toBeNull()
  })
})
