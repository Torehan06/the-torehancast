import { geoPath } from 'd3-geo'
import { feature } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'
import type { KeyboardEvent } from 'react'
import usAtlas from 'us-atlas/states-albers-10m.json'
import type { ParsedSummary } from '../data/parse'
import { leader, party, voteState } from '../data/display'
import { HAS_SENATE_RACE, STATE_BY_FIPS, type UsState } from '../data/states'
import { raceLabel } from './raceLabel'

// us-atlas ships US Census boundaries already projected to Albers USA in a
// 975×610 frame, so the path generator needs no projection and no network.
const topology = usAtlas as unknown as Topology<{ states: GeometryCollection<{ name: string }> }>
const toPath = geoPath()
const SHAPES: { state: UsState; d: string }[] = feature(topology, topology.objects.states)
  .features.flatMap((f) => {
    const state = STATE_BY_FIPS.get(String(f.id)) // drops DC: not a state, no Senate seat
    const d = toPath(f)
    return state && d ? [{ state, d }] : []
  })

interface Props {
  summary: ParsedSummary | null
  selected: string | null
  onSelect: (code: string) => void
}

export function SenateMap({ summary, selected, onSelect }: Props) {
  return (
    <svg className="map" viewBox="0 0 975 610" role="group" aria-label="Map of 2026 Senate races by state">
      {SHAPES.map(({ state, d }) => {
        if (!HAS_SENATE_RACE.has(state.code)) {
          return (
            <path key={state.code} d={d} data-state={state.code} className="state state--neutral" aria-hidden="true">
              <title>{state.name}: no Senate race in 2026</title>
            </path>
          )
        }
        const race = summary?.races.get(state.code)
        const lead = leader(race)
        const cls = [
          'state',
          'state--race',
          lead ? `lead-${party(lead.key)} strength-${lead.strength}` : voteState(race) === 'none' ? 'state--waiting' : 'state--noleader',
          state.code === selected ? 'state--selected' : '',
        ].join(' ')
        const label = raceLabel(state, race, summary)
        const onKey = (e: KeyboardEvent) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onSelect(state.code)
          }
        }
        return (
          <path
            key={state.code}
            d={d}
            data-state={state.code}
            className={cls}
            role="button"
            tabIndex={0}
            aria-label={label}
            aria-pressed={state.code === selected}
            onClick={() => onSelect(state.code)}
            onKeyDown={onKey}
          >
            <title>{label}</title>
          </path>
        )
      })}
    </svg>
  )
}
