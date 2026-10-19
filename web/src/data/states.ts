/**
 * Static facts about the map: the 50 states and which of them elect a senator
 * on Nov 3, 2026 (the 33 Class 2 seats plus the Florida and Ohio specials).
 * This decides only which states are clickable and how they're labelled — never
 * which races are modeled; that comes from the JSON's `modeled` flag.
 */

export interface UsState {
  fips: string
  code: string
  name: string
}

export const STATES: UsState[] = [
  ['01', 'AL', 'Alabama'], ['02', 'AK', 'Alaska'], ['04', 'AZ', 'Arizona'], ['05', 'AR', 'Arkansas'],
  ['06', 'CA', 'California'], ['08', 'CO', 'Colorado'], ['09', 'CT', 'Connecticut'], ['10', 'DE', 'Delaware'],
  ['12', 'FL', 'Florida'], ['13', 'GA', 'Georgia'], ['15', 'HI', 'Hawaii'], ['16', 'ID', 'Idaho'],
  ['17', 'IL', 'Illinois'], ['18', 'IN', 'Indiana'], ['19', 'IA', 'Iowa'], ['20', 'KS', 'Kansas'],
  ['21', 'KY', 'Kentucky'], ['22', 'LA', 'Louisiana'], ['23', 'ME', 'Maine'], ['24', 'MD', 'Maryland'],
  ['25', 'MA', 'Massachusetts'], ['26', 'MI', 'Michigan'], ['27', 'MN', 'Minnesota'], ['28', 'MS', 'Mississippi'],
  ['29', 'MO', 'Missouri'], ['30', 'MT', 'Montana'], ['31', 'NE', 'Nebraska'], ['32', 'NV', 'Nevada'],
  ['33', 'NH', 'New Hampshire'], ['34', 'NJ', 'New Jersey'], ['35', 'NM', 'New Mexico'], ['36', 'NY', 'New York'],
  ['37', 'NC', 'North Carolina'], ['38', 'ND', 'North Dakota'], ['39', 'OH', 'Ohio'], ['40', 'OK', 'Oklahoma'],
  ['41', 'OR', 'Oregon'], ['42', 'PA', 'Pennsylvania'], ['44', 'RI', 'Rhode Island'], ['45', 'SC', 'South Carolina'],
  ['46', 'SD', 'South Dakota'], ['47', 'TN', 'Tennessee'], ['48', 'TX', 'Texas'], ['49', 'UT', 'Utah'],
  ['50', 'VT', 'Vermont'], ['51', 'VA', 'Virginia'], ['53', 'WA', 'Washington'], ['54', 'WV', 'West Virginia'],
  ['55', 'WI', 'Wisconsin'], ['56', 'WY', 'Wyoming'],
].map(([fips, code, name]) => ({ fips, code, name }))

export const STATE_BY_FIPS = new Map(STATES.map((s) => [s.fips, s]))
export const STATE_BY_CODE = new Map(STATES.map((s) => [s.code, s]))

const CLASS_2 = [
  'AL', 'AK', 'AR', 'CO', 'DE', 'GA', 'ID', 'IL', 'IA', 'KS', 'KY', 'LA', 'ME', 'MA', 'MI', 'MN', 'MS',
  'MT', 'NE', 'NH', 'NJ', 'NM', 'NC', 'OK', 'OR', 'RI', 'SC', 'SD', 'TN', 'TX', 'VA', 'WV', 'WY',
]
const SPECIALS = ['FL', 'OH']

export interface SenateRace {
  state: UsState
  special: boolean
}

export const SENATE_RACES_2026: SenateRace[] = [...CLASS_2, ...SPECIALS]
  .map((code) => ({ state: STATE_BY_CODE.get(code)!, special: SPECIALS.includes(code) }))
  .sort((a, b) => a.state.name.localeCompare(b.state.name))

export const HAS_SENATE_RACE = new Set(SENATE_RACES_2026.map((r) => r.state.code))

/**
 * The 13 seats in the model's registry (PLAN.md), featured below the map.
 * This only decides where a race is displayed. Whether it shows a probability
 * still comes from its JSON (`modeled: true` with votes in), never from this list.
 */
export const SWING_SEATS = new Set(['GA', 'NC', 'FL', 'TX', 'OH', 'IA', 'KS', 'SC', 'MI', 'MN', 'ME', 'AK', 'NE'])
