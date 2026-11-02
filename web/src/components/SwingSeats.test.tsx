import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { parseSummary } from '../data/parse'
import { SWING_SEATS } from '../data/states'
import { RaceList } from './RaceList'
import { SwingSeats } from './SwingSeats'

function raw(name: string) {
  return JSON.parse(readFileSync(resolve(__dirname, '../../fixtures', name, 'summary.json'), 'utf8'))
}

function load(name: string) {
  return parseSummary(raw(name))
}

/** Real replay output as a pre-M3 publisher wrote it: no `modeled` flag. */
function preM3(name: string) {
  const summary = raw(name)
  for (const race of summary.states) delete race.modeled
  return parseSummary(summary)
}

function tile(code: string) {
  return document.querySelector(`[data-race="${code}"]`)!
}

describe('SwingSeats', () => {
  it.each(['absent', 'cases/waiting', 'demo'])('counts active seats even with %s data', (name) => {
    const summary = name === 'absent' ? null : load(name)
    render(<SwingSeats summary={summary} selected={null} onSelect={() => {}} />)
    expect(screen.getByRole('heading', { name: '9 swing seats' })).toBeInTheDocument()
    expect([...document.querySelectorAll('.race-item--swing')].map((el) => el.getAttribute('data-race')))
      .toEqual(['AK', 'FL', 'GA', 'IA', 'MN', 'NE', 'NC', 'OH', 'SC'])
    if (name !== 'demo') expect(screen.queryByTestId(/swing-prob-/)).toBeNull()
  })

  it('derives the heading from the displayed active races', () => {
    const membership = vi.spyOn(SWING_SEATS, 'has').mockImplementation((code) => code === 'GA' || code === 'AK')
    try {
      render(<SwingSeats summary={null} selected={null} onSelect={() => {}} />)
      expect(screen.getByRole('heading', { name: '2 swing seats' })).toBeInTheDocument()
      expect(document.querySelectorAll('.race-item--swing')).toHaveLength(2)
    } finally {
      membership.mockRestore()
    }
  })

  it('keeps dropped seats accessible in the other-races list', () => {
    render(<RaceList summary={null} selected={null} onSelect={() => {}} />)
    for (const name of ['Texas', 'Kansas', 'Michigan', 'Maine']) {
      expect(screen.getByRole('button', { name: new RegExp(`${name} Senate:`) })).toBeInTheDocument()
    }
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
    // Exercise the same RCV guard with Alaska, which remains active.
    render(<SwingSeats summary={load('demo')} selected={null} onSelect={() => {}} />)
    expect(screen.queryByTestId('swing-prob-AK')).toBeNull()
    expect(tile('AK')).toHaveTextContent('leads with 47.0% of the vote')
  })

  it('shows no probability for pre-M3 data without the modeled flag', () => {
    render(<SwingSeats summary={preM3('replay-ga')} selected={null} onSelect={() => {}} />)
    expect(screen.queryByTestId('swing-prob-GA')).toBeNull()
  })
})
