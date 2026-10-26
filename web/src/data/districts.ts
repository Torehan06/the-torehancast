/**
 * The 435 House seats on Nov 3, 2026 and their canonical race IDs, copied from
 * src/torehancast/districts.py (tests/unit/test_districts.py fails if they drift).
 * 2020-census apportionment: lines may change mid-decade, seat counts may not.
 *
 *   houseRaceId('NC', 1) -> '2026-NC-H01'
 *   houseRaceId('AK', 1) -> '2026-AK-HAL'   (at-large)
 */

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
