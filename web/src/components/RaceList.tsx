import type { ParsedSummary } from '../data/parse'
import { formatProbability, formatShare, leader, party } from '../data/display'
import { SENATE_RACES_2026, SWING_SEATS } from '../data/states'
import { raceLabel, raceStatus } from './raceLabel'

interface Props {
  summary: ParsedSummary | null
  selected: string | null
  onSelect: (code: string) => void
}

/**
 * The other 22 Senate races as plain buttons (the swing seats have their own
 * tiles). Small states (RI, DE) are hard to tap on a phone map; this list and
 * the tiles are the reliable way in, and they carry the number behind each colour.
 */
export function RaceList({ summary, selected, onSelect }: Props) {
  return (
    <ul className="race-list" aria-label="Other 2026 Senate races">
      {SENATE_RACES_2026.filter(({ state }) => !SWING_SEATS.has(state.code)).map(({ state, special }) => {
        const race = summary?.races.get(state.code)
        const lead = leader(race)
        const label = raceLabel(state, race, summary)
        // With a leader, the number gets its own column and the text names who and what.
        const detail = lead
          ? `${lead.name}, ${lead.basis === 'probability' ? 'chance to win' : 'share of the vote'}`
          : raceStatus(state, race, summary)
        const value = lead ? (lead.basis === 'probability' ? formatProbability(lead.value) : formatShare(lead.value)) : null
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
              {value && <span className={`race-item__value lead-${party(lead!.key)}`}>{value}</span>}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
