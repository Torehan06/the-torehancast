import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RacePanel } from './RacePanel'
import { DistrictPanel } from './DistrictPanel'
import { SwingSeats } from './SwingSeats'
import { RaceList } from './RaceList'
import { SenateMap } from './SenateMap'
import { HouseTiles } from './HouseTiles'
import { NO_VOTES } from '../data/display'

it.each(['TX', 'KS', 'MI', 'ME', 'AL', 'WY'])('%s panel says Not tracked when absent', (code) => {
  render(<RacePanel code={code} summary={null} onClose={() => {}} />)
  expect(screen.getByTestId('race-panel')).toHaveTextContent('Not tracked')
  expect(screen.getByTestId('race-panel')).not.toHaveTextContent(NO_VOTES)
})

it.each(['GA', 'AK', 'NE'])('%s panel keeps the tracked waiting wording', (code) => {
  render(<RacePanel code={code} summary={null} onClose={() => {}} />)
  expect(screen.getByTestId('race-panel')).toHaveTextContent(NO_VOTES)
})

it.each(['TX-01', 'KS-01', 'MI-01', 'ME-02', 'WY-AL'])('%s House panel says Not tracked', (districtKey) => {
  render(<DistrictPanel districtKey={districtKey} house={null} onClose={() => {}} />)
  expect(screen.getByTestId('race-panel')).toHaveTextContent('Not tracked')
})

it('AK-AL stays tracked and explains withheld win probability even before a file exists', () => {
  render(<DistrictPanel districtKey="AK-AL" house={null} onClose={() => {}} />)
  expect(screen.getByTestId('race-panel')).toHaveTextContent(NO_VOTES)
  expect(screen.getByTestId('race-panel')).toHaveTextContent('Win probability withheld: ranked-choice simulation is not yet available.')
})

describe('all race surfaces', () => {
  it('uses distinct map fills, tooltips, list text and accessible names', () => {
    const { container } = render(<><SenateMap summary={null} selected={null} onSelect={() => {}} /><SwingSeats summary={null} selected={null} onSelect={() => {}} /><RaceList summary={null} selected={null} onSelect={() => {}} /><HouseTiles house={null} selected={null} onSelect={() => {}} /></>)
    for (const code of ['TX', 'KS', 'MI', 'ME']) {
      expect(container.querySelector(`[data-state="${code}"]`)).toHaveClass('state--not-tracked')
      expect(container.querySelector(`[data-state="${code}"] title`)).toHaveTextContent('Not tracked')
      expect(container.querySelector(`[data-race="${code}"]`)).toHaveTextContent('Not tracked')
    }
    for (const code of ['GA', 'AK']) expect(container.querySelector(`[data-race="${code}"]`)).toHaveTextContent(NO_VOTES)
    expect(container.querySelector('[data-district="TX-01"]')).toHaveClass('tile--not-tracked')
    expect(container.querySelector('[data-district="AK-AL"]')).toHaveClass('tile--waiting')
  })
})
