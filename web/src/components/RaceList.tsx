import type { ParsedSummary } from '../data/parse'
import { leader, party } from '../data/display'
import { SENATE_RACES_2026 } from '../data/states'
import { raceLabel, raceStatus } from './raceLabel'

interface Props {
  summary: ParsedSummary | null
  selected: string | null
  onSelect: (code: string) => void
}

/**
 * Every 2026 Senate race as a plain button. Small states (RI, DE) are hard to
 * tap on a phone map; this list is the reliable way in, and it carries the
 * explicit number behind each state's colour.
 */
export function RaceList({ summary, selected, onSelect }: Props) {
  return (
    <ul className="race-list" aria-label="All 2026 Senate races">
      {SENATE_RACES_2026.map(({ state, special }) => {
        const race = summary?.races.get(state.code)
        const lead = leader(race)
        const label = raceLabel(state, race, summary)
        const detail = raceStatus(state, race, summary)
        return (
          <li key={state.code}>
            <button
              type="button"
              className={`race-item ${state.code === selected ? 'race-item--selected' : ''}`}
              data-race={state.code}
              aria-pressed={state.code === selected}
              aria-label={label}
              onClick={() => onSelect(state.code)}
            >
              <span className={`swatch ${lead ? `lead-${party(lead.key)} strength-${lead.strength}` : 'swatch--none'}`} />
              <span className="race-item__name">
                {state.name}
                {special && <span className="tag">special</span>}
              </span>
              <span className="race-item__detail">{detail}</span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
