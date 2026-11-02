/**
 * The 435 House seats on Nov 3, 2026 and their canonical race IDs, copied from
 * src/torehancast/districts.py (tests/unit/test_districts.py fails if they drift).
 * 2020-census apportionment: lines may change mid-decade, seat counts may not.
 *
 *   houseRaceId('NC', 1) -> '2026-NC-H01'
 *   houseRaceId('AK', 1) -> '2026-AK-HAL'   (at-large)
 */

import { STATE_BY_CODE } from './states'
import houseTiles from './houseTiles.json'

export const YEAR = 2026

export const APPORTIONMENT: Record<string, number> = {
  AL: 7, AK: 1, AZ: 9, AR: 4, CA: 52, CO: 8, CT: 5, DE: 1, FL: 28, GA: 14,
  HI: 2, ID: 2, IL: 17, IN: 9, IA: 4, KS: 4, KY: 6, LA: 6, ME: 2, MD: 8,
  MA: 9, MI: 13, MN: 8, MS: 4, MO: 8, MT: 2, NE: 3, NV: 4, NH: 2, NJ: 12,
  NM: 3, NY: 26, NC: 14, ND: 1, OH: 15, OK: 5, OR: 6, PA: 17, RI: 2, SC: 7,
  SD: 1, TN: 9, TX: 38, UT: 4, VT: 1, VA: 11, WA: 10, WV: 2, WI: 8, WY: 1,
}

export const atLarge = (state: string): boolean => APPORTIONMENT[state] === 1

export function houseRaceId(state: string, district: number): string {
  const seats = APPORTIONMENT[state]
  if (!seats || district < 1 || district > seats) {
    throw new Error(`${state} has ${seats ?? 0} House seat(s), not district ${district}`)
  }
  return seats === 1 ? `${YEAR}-${state}-HAL` : `${YEAR}-${state}-H${String(district).padStart(2, '0')}`
}

/** District label for display: 'NC-1', or 'AK-AL' for an at-large seat. */
export function districtLabel(state: string, district: number): string {
  return atLarge(state) ? `${state}-AL` : `${state}-${district}`
}

export const HOUSE_RACE_IDS: string[] = Object.keys(APPORTIONMENT)
  .sort()
  .flatMap((state) => Array.from({ length: APPORTIONMENT[state] }, (_, i) => houseRaceId(state, i + 1)))

function ordinal(n: number): string {
  const tens = n % 100
  if (tens >= 11 && tens <= 13) return `${n}th`
  return `${n}${['th', 'st', 'nd', 'rd'][n % 10] ?? 'th'}`
}

/** District name for display: "North Carolina's 1st District", "Alaska's at-large district". */
export function districtName(state: string, district: number): string {
  const name = STATE_BY_CODE.get(state)?.name ?? state
  return atLarge(state) ? `${name}'s at-large district` : `${name}'s ${ordinal(district)} District`
}

/** One seat on the tile cartogram, with everything the page needs to look up its race. */
export interface District {
  /** Map and URL key: 'NC-01', or 'AK-AL' for an at-large seat. */
  key: string
  state: string
  number: number
  raceId: string
  /** Short label: 'NC-1', 'AK-AL'. */
  label: string
  name: string
  x: number
  y: number
}

export const DISTRICTS: District[] = houseTiles.tiles.map(({ id, state, x, y }) => {
  const number = id.endsWith('-AL') ? 1 : Number(id.slice(3))
  return {
    key: id,
    state,
    number,
    raceId: houseRaceId(state, number),
    label: districtLabel(state, number),
    name: districtName(state, number),
    x,
    y,
  }
})

export const DISTRICT_BY_KEY = new Map(DISTRICTS.map((d) => [d.key, d]))
export const TILE_GRID = { width: houseTiles.width, height: houseTiles.height }

export type Direction = 'ArrowUp' | 'ArrowDown' | 'ArrowLeft' | 'ArrowRight'

const STEP: Record<Direction, [number, number]> = {
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
}

/**
 * The tile an arrow key lands on: the closest one that way, preferring the same
 * row or column so a straight run stays straight across gaps in the grid.
 * Null at the edge of the map.
 */
export function tileInDirection(from: District, direction: Direction): District | null {
  const [dx, dy] = STEP[direction]
  let best: District | null = null
  let bestScore = Infinity
  for (const d of DISTRICTS) {
    const along = (d.x - from.x) * dx + (d.y - from.y) * dy
    if (along <= 0) continue
    const across = Math.abs((d.x - from.x) * dy) + Math.abs((d.y - from.y) * dx)
    const score = along + across * 3
    if (score < bestScore) {
      best = d
      bestScore = score
    }
  }
  return best
}
