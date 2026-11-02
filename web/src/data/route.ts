/**
 * What the URL hash selects. `#GA` is a Senate race, `#NC-01` and `#AK-AL` a House
 * district, `#house` the House view with nothing selected. Anything else is the
 * Senate map, so an old or mistyped link still lands on a working page.
 */
import { DISTRICT_BY_KEY } from './districts'
import { HAS_SENATE_RACE } from './states'

export type View = 'senate' | 'house'

export interface Route {
  view: View
  /** A state code in the Senate view, a district key in the House view. */
  selected: string | null
}

export const HOUSE_HASH = 'house'

export function parseRoute(hash: string): Route {
  const raw = hash.replace(/^#/, '')
  if (raw.toLowerCase() === HOUSE_HASH) return { view: 'house', selected: null }
  const code = raw.toUpperCase()
  if (DISTRICT_BY_KEY.has(code)) return { view: 'house', selected: code }
  return { view: 'senate', selected: HAS_SENATE_RACE.has(code) ? code : null }
}

/** The hash for a route, with no leading '#'; empty for the bare Senate map. */
export function routeHash({ view, selected }: Route): string {
  return selected ?? (view === 'house' ? HOUSE_HASH : '')
}
