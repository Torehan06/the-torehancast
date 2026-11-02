/**
 * The 2020-census apportionment (435 seats, in force 2022-2030), mirrored from
 * src/torehancast/districts.py so the geography tests can check IDs without the registry.
 * District keys here are map keys ('NC-01', at-large 'AK-AL'), not race IDs.
 */

export const APPORTIONMENT: Record<string, number> = {
  AL: 7, AK: 1, AZ: 9, AR: 4, CA: 52, CO: 8, CT: 5, DE: 1, FL: 28, GA: 14,
  HI: 2, ID: 2, IL: 17, IN: 9, IA: 4, KS: 4, KY: 6, LA: 6, ME: 2, MD: 8,
  MA: 9, MI: 13, MN: 8, MS: 4, MO: 8, MT: 2, NE: 3, NV: 4, NH: 2, NJ: 12,
  NM: 3, NY: 26, NC: 14, ND: 1, OH: 15, OK: 5, OR: 6, PA: 17, RI: 2, SC: 7,
  SD: 1, TN: 9, TX: 38, UT: 4, VT: 1, VA: 11, WA: 10, WV: 2, WI: 8, WY: 1,
}

export const districtKey = (state: string, n: number): string =>
  APPORTIONMENT[state] === 1 ? `${state}-AL` : `${state}-${String(n).padStart(2, '0')}`

export const districtKeys = (): string[] =>
  Object.keys(APPORTIONMENT)
    .sort()
    .flatMap((s) => Array.from({ length: APPORTIONMENT[s] }, (_, i) => districtKey(s, i + 1)))
