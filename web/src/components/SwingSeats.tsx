import { formatProbability, leader, party, voteState } from '../data/display'
import type { ParsedSummary } from '../data/parse'
import { SENATE_RACES_2026, SWING_SEATS } from '../data/states'
import { raceLabel, raceStatus } from './raceLabel'

interface Props {
  summary: ParsedSummary | null
  selected: string | null
  onSelect: (code: string) => void
}

/**
 * The 13 forecast seats as tiles, each led by the favourite's win probability
 * in big type and party colour. Tiles stay in alphabetical order: a grid that
 * re-sorts itself every 20 seconds is impossible to follow on election night.
 */
export function SwingSeats({ summary, selected, onSelect }: Props) {
  const seats = SENATE_RACES_2026.filter(({ state }) => SWING_SEATS.has(state.code))
  return (
    <section className="swing" aria-labelledby="swing-title">
      <h2 id="swing-title" className="list-title">
        13 swing seats
      </h2>
      <p className="swing__intro">The races the model forecasts. The big number is the favourite’s chance of winning.</p>
      <ul className="swing__grid">
        {seats.map(({ state, special }) => {
          const race = summary?.races.get(state.code)
          const lead = leader(race)
          // Only a published win probability gets the big number, never a vote share.
          const forecast = lead?.basis === 'probability' ? lead : null
          const detail = forecast ? `${forecast.name} to win` : raceStatus(state, race, summary)
          const cls = [
            'race-item',
            'race-item--swing',
            forecast ? `lead-${party(forecast.key)}` : '',
            voteState(race) === 'none' ? 'race-item--empty' : '',
            state.code === selected ? 'race-item--selected' : '',
          ].join(' ')
          return (
            <li key={state.code}>
              <button
                type="button"
                className={cls}
                data-race={state.code}
                aria-pressed={state.code === selected}
                aria-label={raceLabel(state, race, summary)}
                onClick={() => onSelect(state.code)}
              >
                <span className="race-item__name">
                  {state.name}
                  {special && <span className="tag">special</span>}
                </span>
                {forecast && (
                  <span className="swing__prob" data-testid={`swing-prob-${state.code}`}>
                    {formatProbability(forecast.value)}
                  </span>
                )}
                <span className="race-item__detail">{detail}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
