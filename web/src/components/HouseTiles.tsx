import { isNotTracked } from '../data/coverage'
import { memo, useState, type KeyboardEvent } from 'react'
import { leader, party, voteState } from '../data/display'
import { DISTRICT_BY_KEY, DISTRICTS, TILE_GRID, tileInDirection, type Direction, type District } from '../data/districts'
import type { ParsedHouse } from '../data/parse'
import { districtLabelText } from './raceLabel'

const CELL = 20

/** State borders: every tile edge whose neighbour across it is in another state. */
const STATE_BORDERS = (() => {
  const stateAt = new Map(DISTRICTS.map((d) => [`${d.x},${d.y}`, d.state]))
  const edges: string[] = []
  for (const { x, y, state } of DISTRICTS) {
    const [left, top] = [x * CELL, y * CELL]
    if (stateAt.get(`${x - 1},${y}`) !== state) edges.push(`M${left} ${top}v${CELL}`)
    if (stateAt.get(`${x + 1},${y}`) !== state) edges.push(`M${left + CELL} ${top}v${CELL}`)
    if (stateAt.get(`${x},${y - 1}`) !== state) edges.push(`M${left} ${top}h${CELL}`)
    if (stateAt.get(`${x},${y + 1}`) !== state) edges.push(`M${left} ${top + CELL}h${CELL}`)
  }
  return edges.join('')
})()

/** On a phone the squares are too small to print on, so the bigger blocks get their state code instead. */
const STATE_LABELS = (() => {
  const blocks = new Map<string, District[]>()
  for (const d of DISTRICTS) blocks.set(d.state, [...(blocks.get(d.state) ?? []), d])
  return [...blocks.entries()]
    .filter(([, tiles]) => tiles.length >= 4)
    .map(([state, tiles]) => ({
      state,
      x: (tiles.reduce((sum, t) => sum + t.x, 0) / tiles.length + 0.5) * CELL,
      y: (tiles.reduce((sum, t) => sum + t.y, 0) / tiles.length + 0.5) * CELL,
    }))
})()

interface Props {
  house: ParsedHouse | null
  selected: string | null
  onSelect: (key: string) => void
}

/**
 * The 435 districts as a tile cartogram. One tab stop, arrow keys move between
 * tiles: 435 tab stops would make everything below the map unreachable by keyboard.
 */
export const HouseTiles = memo(function HouseTiles({ house, selected, onSelect }: Props) {
  // The one tab stop: where the keyboard last was, or the district in the URL on arrival.
  const [cursor, setCursor] = useState(selected && DISTRICT_BY_KEY.has(selected) ? selected : DISTRICTS[0].key)

  const onKeyDown = (e: KeyboardEvent<SVGGElement>, district: District) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onSelect(district.key)
    } else if (e.key.startsWith('Arrow')) {
      e.preventDefault()
      const next = tileInDirection(district, e.key as Direction)
      if (next) e.currentTarget.ownerSVGElement?.querySelector<SVGGElement>(`[data-district="${next.key}"]`)?.focus()
    }
  }

  return (
    <svg
      className="tiles__map"
      viewBox={`0 0 ${TILE_GRID.width * CELL} ${TILE_GRID.height * CELL}`}
      role="group"
      aria-label="Map of the 435 House districts, one square each. Use the arrow keys to move between districts."
    >
      <defs>
        {/* Races with no votes yet: hatched, like the Senate map's unmarked ballot. */}
        <pattern id="hatch-tile" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="5" height="5" className="hatch__bg" />
          <line x1="0" y1="0" x2="0" y2="5" className="hatch__line" />
        </pattern>
      </defs>
      {DISTRICTS.map((district) => {
        const race = house?.races.get(district.raceId)
        const invalid = house?.invalid.includes(district.raceId) ?? false
        const lead = leader(race)
        const cls = [
          'tile',
          lead ? `lead-${party(lead.key)} strength-${lead.strength}` : isNotTracked(district.raceId, race) ? 'tile--not-tracked' : voteState(race) === 'none' ? 'tile--waiting' : 'tile--noleader',
          district.key === selected ? 'tile--selected' : '',
        ].join(' ')
        const label = districtLabelText(district, race, invalid)
        return (
          <g
            key={district.key}
            data-district={district.key}
            className={cls}
            role="button"
            tabIndex={district.key === cursor ? 0 : -1}
            aria-label={label}
            aria-pressed={district.key === selected}
            onClick={() => onSelect(district.key)}
            onFocus={() => setCursor(district.key)}
            onKeyDown={(e) => onKeyDown(e, district)}
          >
            <title>{label}</title>
            <rect className="tile__box" x={district.x * CELL + 1} y={district.y * CELL + 1} width={CELL - 2} height={CELL - 2} rx="2" />
            <text className="tile__label" x={(district.x + 0.5) * CELL} y={(district.y + 0.5) * CELL} aria-hidden="true">
              {district.number === 1 ? district.state : district.number}
            </text>
          </g>
        )
      })}
      <path className="tiles__borders" d={STATE_BORDERS} aria-hidden="true" />
      <g className="tiles__states" aria-hidden="true">
        {STATE_LABELS.map(({ state, x, y }) => (
          <text key={state} x={x} y={y}>
            {state}
          </text>
        ))}
      </g>
    </svg>
  )
})
