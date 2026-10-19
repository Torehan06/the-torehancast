import type { Race } from '../data/contract'
import { formatProbability, formatShare, leader, NO_VOTES, voteState } from '../data/display'
import type { ParsedSummary } from '../data/parse'
import type { UsState } from '../data/states'

/**
 * One line of text for a race, used by the race list and the map's accessible
 * names. Always states the number behind the colour, and what kind of number.
 */
export function raceStatus(state: UsState, race: Race | undefined, summary: ParsedSummary | null): string {
  if (summary?.invalid.includes(state.code)) return 'data unavailable'
  const votes = voteState(race)
  if (votes === 'none') return NO_VOTES
  const lead = leader(race)
  if (!lead) return votes === 'unknown' ? 'no estimate yet' : 'votes reported, no clear leader'
  return lead.basis === 'probability'
    ? `${lead.name}: ${formatProbability(lead.value)} chance to win`
    : `${lead.name} leads with ${formatShare(lead.value)} of the vote`
}

export function raceLabel(state: UsState, race: Race | undefined, summary: ParsedSummary | null): string {
  return `${state.name} Senate: ${raceStatus(state, race, summary)}`
}
