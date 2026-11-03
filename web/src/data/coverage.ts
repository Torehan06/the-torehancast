import { trackedRaceIds, rankedChoiceRaceIds } from 'virtual:coverage'
import type { Race } from './contract'
import { isRcv, voteState } from './display'

const tracked = new Set(trackedRaceIds)
const rankedChoice = new Set(rankedChoiceRaceIds)
export const NOT_TRACKED = 'Not tracked'
export const RCV_UNAVAILABLE = 'Win probability withheld: ranked-choice simulation is not yet available.'

/** Missing/zero-count data cannot tell us whether a source exists; use config. */
export function isNotTracked(raceId: string, race: Race | undefined): boolean {
  // Preserve valid published results, including replays outside live coverage.
  return !tracked.has(raceId) && voteState(race) === 'none'
}

export function rcvUnavailable(raceId: string, race: Race | undefined): boolean {
  if (!race || race.status === 'waiting' || voteState(race) === 'none') return rankedChoice.has(raceId)
  return isRcv(race) && race.rcv_status === 'awaiting_first_choices' && Object.values(race.p_win).every((p) => p === null)
}
