import { isNotTracked } from '../data/coverage'
import { memo, useState } from 'react'
import { formatProbability, formatShare, leader, party, showsProbabilities } from '../data/display'
import { DISTRICT_BY_KEY, DISTRICTS, type District } from '../data/districts'
import type { ParsedHouse } from '../data/parse'
import { STATES } from '../data/states'
import { districtLabelText, statusLine } from './raceLabel'

interface Props {
  house: ParsedHouse | null
  selected: string | null
  onSelect: (key: string) => void
}

const SEATS = new Map<string, District[]>()
for (const d of DISTRICTS) SEATS.set(d.state, [...(SEATS.get(d.state) ?? []), d])
for (const seats of SEATS.values()) seats.sort((a, b) => a.number - b.number)

function DistrictRow({ district, house, selected, onSelect }: { district: District } & Props) {
  const race = house?.races.get(district.raceId)
  const invalid = house?.invalid.includes(district.raceId) ?? false
  const lead = leader(race)
  // With a leader, the number gets its own column and the text names who and what.
  const detail = lead
    ? `${lead.name}, ${lead.basis === 'probability' ? 'chance to win' : 'share of the vote'}`
    : statusLine(race, invalid, district.raceId)
  const value = lead ? (lead.basis === 'probability' ? formatProbability(lead.value) : formatShare(lead.value)) : null
  return (
    <li>
      <button
        type="button"
        className={`race-item ${district.key === selected ? 'race-item--selected' : ''}`}
        data-race={district.key}
        aria-pressed={district.key === selected}
        aria-label={districtLabelText(district, race, invalid)}
        onClick={() => onSelect(district.key)}
      >
        <span className={`swatch ${lead ? `lead-${party(lead.key)} strength-${lead.strength}` : isNotTracked(district.raceId, race) ? 'state--not-tracked' : 'swatch--none'}`} />
        <span className="race-item__name">{district.label}</span>
        <span className="race-item__detail">{detail}</span>
        {value && <span className={`race-item__value lead-${party(lead!.key)}`}>{value}</span>}
      </button>
    </li>
  )
}

/**
 * The text beside the tiles: the number behind every forecast colour, and a state
 * picker that makes each district reachable where the squares are too small to tap.
 * Rows stay in a fixed order: a list that re-sorts itself every 20 seconds is
 * impossible to follow on election night.
 */
export const HouseLists = memo(function HouseLists({ house, selected, onSelect }: Props) {
  const [chosen, setChosen] = useState('')
  const state = chosen || (selected ? DISTRICT_BY_KEY.get(selected)?.state : '') || ''
  const forecasts = DISTRICTS.filter((d) => showsProbabilities(house?.races.get(d.raceId)))
  const rowProps = { house, selected, onSelect }

  return (
    <>
      <section className="house-browse" aria-labelledby="browse-title">
        <h2 id="browse-title" className="list-title">
          Browse by state
        </h2>
        <label className="house-browse__label">
          <span>State</span>
          <select value={state} onChange={(e) => setChosen(e.target.value)} data-testid="state-picker">
            <option value="">Choose a state</option>
            {STATES.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        {state && (
          <ul className="race-list" aria-label={`House districts in ${state}`} data-testid="state-districts">
            {(SEATS.get(state) ?? []).map((d) => (
              <DistrictRow key={d.key} district={d} {...rowProps} />
            ))}
          </ul>
        )}
      </section>

      <section className="house-forecasts" aria-labelledby="forecasts-title">
        <h2 id="forecasts-title" className="list-title">
          Forecast districts with votes in
        </h2>
        {forecasts.length > 0 ? (
          <ul className="race-list" aria-label="House districts with a forecast" data-testid="house-forecasts">
            {forecasts.map((d) => (
              <DistrictRow key={d.key} district={d} {...rowProps} />
            ))}
          </ul>
        ) : (
          <p className="swing__intro">The districts the model forecasts appear here once they report votes.</p>
        )}
      </section>
    </>
  )
})
