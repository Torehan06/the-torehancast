import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { trackedRaceIds } from 'virtual:coverage'
import { DISTRICTS } from '../data/districts'
import { NO_VOTES } from '../data/display'
import { parseHouse } from '../data/parse'
import { HouseLists } from './HouseLists'
import { HouseTiles } from './HouseTiles'

const raw = JSON.parse(readFileSync(resolve(__dirname, '../../fixtures/cases/house/house.json'), 'utf8'))
const house = parseHouse(raw)

const tiles = (container: HTMLElement) => [...container.querySelectorAll('[data-district]')]
const tile = (container: HTMLElement, key: string) => container.querySelector(`[data-district="${key}"]`)!

describe('HouseTiles', () => {
  it('draws 435 tiles, each with a text label and a name', () => {
    const { container } = render(<HouseTiles house={house} selected={null} onSelect={() => {}} />)
    expect(tiles(container)).toHaveLength(435)
    for (const el of tiles(container)) {
      expect(el.querySelector('text')?.textContent).toBeTruthy()
      expect(el.getAttribute('aria-label')).toBeTruthy()
    }
  })

  it('with no house.json, coverage distinguishes waiting from Not tracked', () => {
    const { container } = render(<HouseTiles house={null} selected={null} onSelect={() => {}} />)
    for (const el of tiles(container)) {
      const district = DISTRICTS.find((d) => d.key === el.getAttribute('data-district'))!
      const tracked = trackedRaceIds.includes(district.raceId)
      expect(el).toHaveClass(tracked ? 'tile--waiting' : 'tile--not-tracked')
      expect(el.getAttribute('aria-label')).toContain(tracked ? NO_VOTES : 'Not tracked')
    }
  })

  it('an untracked race absent from house.json is distinct beside coloured ones', () => {
    const { container } = render(<HouseTiles house={house} selected={null} onSelect={() => {}} />)
    expect(tile(container, 'WY-AL')).toHaveClass('tile--not-tracked')
    expect(tile(container, 'NC-01')).toHaveClass('lead-D')
  })

  it('colour never comes without the number behind it', () => {
    const { container } = render(<HouseTiles house={house} selected={null} onSelect={() => {}} />)
    const coloured = tiles(container).filter((el) => /lead-/.test(el.getAttribute('class') ?? ''))
    expect(coloured.length).toBeGreaterThan(5)
    for (const el of coloured) {
      expect(el.getAttribute('aria-label')).toMatch(/\d+(\.\d)?%/)
      expect(el.querySelector('title')?.textContent).toMatch(/\d+(\.\d)?%/)
    }
  })

  it('names what kind of number it is: chance for a forecast, share for a count', () => {
    const { container } = render(<HouseTiles house={house} selected={null} onSelect={() => {}} />)
    expect(tile(container, 'NC-01').getAttribute('aria-label')).toContain('62% chance to win')
    expect(tile(container, 'IL-01').getAttribute('aria-label')).toContain('65.5% of the vote')
    expect(tile(container, 'IL-01').getAttribute('aria-label')).not.toContain('chance')
  })

  it('an RCV race with null probabilities is not coloured as a forecast', () => {
    const { container } = render(<HouseTiles house={house} selected={null} onSelect={() => {}} />)
    expect(tile(container, 'AK-AL')).toHaveClass('strength-light')
    expect(tile(container, 'AK-AL').getAttribute('aria-label')).not.toContain('chance')
  })

  it('is one tab stop; Enter and Space select, arrow keys move', () => {
    const onSelect = vi.fn()
    const { container } = render(<HouseTiles house={house} selected={null} onSelect={onSelect} />)
    const stops = tiles(container).filter((el) => el.getAttribute('tabindex') === '0')
    expect(stops).toHaveLength(1)
    const first = stops[0] as SVGGElement
    first.focus()
    fireEvent.keyDown(first, { key: 'Enter' })
    expect(onSelect).toHaveBeenLastCalledWith(first.getAttribute('data-district'))
    fireEvent.keyDown(first, { key: ' ' })
    expect(onSelect).toHaveBeenCalledTimes(2)
    fireEvent.keyDown(first, { key: 'ArrowDown' })
    expect(document.activeElement).not.toBe(first)
    expect(document.activeElement).toHaveAttribute('data-district')
    expect(tiles(container).filter((el) => el.getAttribute('tabindex') === '0')).toEqual([document.activeElement])
  })

  it('a click selects', () => {
    const onSelect = vi.fn()
    const { container } = render(<HouseTiles house={house} selected={null} onSelect={onSelect} />)
    fireEvent.click(tile(container, 'PA-07'))
    expect(onSelect).toHaveBeenCalledWith('PA-07')
  })

  it('marks the selected tile', () => {
    const { container } = render(<HouseTiles house={house} selected="PA-07" onSelect={() => {}} />)
    expect(tile(container, 'PA-07')).toHaveAttribute('aria-pressed', 'true')
    expect(tile(container, 'PA-07')).toHaveAttribute('tabindex', '0')
  })
})

describe('HouseLists', () => {
  it('the state picker lists every district of a state, with the number beside the colour', () => {
    const onSelect = vi.fn()
    render(<HouseLists house={house} selected={null} onSelect={onSelect} />)
    expect(screen.queryByTestId('state-districts')).toBeNull()
    fireEvent.change(screen.getByTestId('state-picker'), { target: { value: 'IL' } })
    const rows = screen.getByTestId('state-districts').querySelectorAll('button')
    expect(rows).toHaveLength(17)
    expect(rows[0]).toHaveTextContent('IL-1')
    expect(rows[0]).toHaveTextContent('65.5%')
    expect(rows[16]).toHaveTextContent('Not tracked')
    fireEvent.click(rows[0])
    expect(onSelect).toHaveBeenCalledWith('IL-01')
  })

  it('the forecast list shows only modeled races with votes in, never a results-only race', () => {
    render(<HouseLists house={house} selected={null} onSelect={() => {}} />)
    const list = screen.getByTestId('house-forecasts')
    const keys = [...list.querySelectorAll('button')].map((b) => b.getAttribute('data-race'))
    expect(keys.sort()).toEqual(['AK-AL', 'IA-01', 'ME-02', 'NC-01', 'PA-07', 'SC-01'])
  })

  it('with no house.json the forecast list explains itself instead of showing an empty table', () => {
    render(<HouseLists house={null} selected={null} onSelect={() => {}} />)
    expect(screen.queryByTestId('house-forecasts')).toBeNull()
    expect(screen.getByText(/appear here once they report votes/)).toBeInTheDocument()
  })
})
