/**
 * Display rules (PLAN.md "Map display rules" and F3). These functions only pick
 * which published numbers to show; none of them estimates anything.
 */
import type { LiveRace, PluralityRace, Race, RcvRace } from './contract'

export const NO_VOTES = 'no votes reported for this race'

export type VoteState = 'none' | 'some' | 'unknown'

/**
 * Whether votes have been reported. 'unknown' is a payload that doesn't carry
 * vote counts at all (an RCV race before M3); the page then shows what it has
 * and doesn't claim "no votes".
 */
export function voteState(race: Race | undefined): VoteState {
  if (!race || race.status === 'waiting') return 'none'
  if (race.votes) return Object.values(race.votes).some((v) => v > 0) ? 'some' : 'none'
  if ('reported_votes' in race) return race.reported_votes > 0 ? 'some' : 'none'
  return 'unknown'
}

export function isRcv(race: Race): race is RcvRace {
  return race.status === 'live' && 'rcv_status' in race
}

export function isPlurality(race: Race): race is PluralityRace {
  return race.status === 'live' && 'margin' in race
}

/**
 * Probabilities appear only for an explicit `modeled: true` with votes in.
 * Requiring votes is defence in depth for the private priors: a zero-vote
 * probability is pure prior, and the live publisher's waiting gate should never
 * send one — but replays do, and a mis-gated live file must not display it.
 */
export function showsProbabilities(race: Race | undefined): race is PluralityRace | RcvRace {
  if (!race || race.status !== 'live' || race.modeled !== true) return false
  if (!isPlurality(race) && !isRcv(race)) return false
  return voteState(race) !== 'none'
}

export type Party = 'D' | 'R' | 'other'

/** Party colour for a candidate key. Keys are sides ("D", "R") in the publisher. */
export function party(key: string): Party {
  return key === 'D' || key === 'R' ? key : 'other'
}

export type Strength = 'strong' | 'medium' | 'light'

export interface Leader {
  key: string
  name: string
  /** What the number is, so the label never leaves it ambiguous. */
  basis: 'probability' | 'vote_share'
  value: number
  strength: Strength
}

function argmax(values: Record<string, number | null>): [string, number] | null {
  let best: [string, number] | null = null
  let tied = false
  for (const [k, v] of Object.entries(values)) {
    if (v === null) continue
    if (!best || v > best[1]) {
      best = [k, v]
      tied = false
    } else if (v === best[1]) {
      tied = true
    }
  }
  return best && !tied ? best : null
}

/**
 * Who the map colours a state for, and by what number. A modeled race uses its
 * published win probability; a results-only race its published vote share (and
 * always the lightest shade, so a count lead never looks like a forecast). An
 * RCV race whose probabilities are still null also falls back to its vote lead.
 * Ties and unknowns return null and the state renders as "no leader".
 */
export function leader(race: Race | undefined): Leader | null {
  if (!race || race.status !== 'live' || voteState(race) === 'none') return null
  const live = race as LiveRace
  if (showsProbabilities(live)) {
    const top = argmax(live.p_win)
    if (top) {
      const [key, value] = top
      const strength: Strength = value >= 0.95 ? 'strong' : value >= 0.75 ? 'medium' : 'light'
      return { key, name: live.candidates[key] ?? key, basis: 'probability', value, strength }
    }
    // No probability yet (RCV nulls): fall back to the published vote lead.
  }
  if (live.vote_share) {
    const top = argmax(live.vote_share)
    if (!top) return null
    return { key: top[0], name: live.candidates[top[0]] ?? top[0], basis: 'vote_share', value: top[1], strength: 'light' }
  }
  return null
}

/** Probability as a whole percentage, never claiming certainty the model can't have. */
export function formatProbability(p: number | null): string {
  if (p === null) return 'not yet estimated'
  if (p > 0.99) return '>99%'
  if (p < 0.01) return '<1%'
  return `${Math.round(p * 100)}%`
}

export function formatShare(p: number): string {
  return `${(p * 100).toFixed(1)}%`
}

export function formatCount(n: number): string {
  return n.toLocaleString('en-US')
}

/** Margin is non-R minus R (two-party share). Labelled by side, e.g. "D+1.0". */
export function formatMargin(m: number, nonR: string): string {
  const pts = Math.abs(m * 100).toFixed(1)
  if (pts === '0.0') return 'Even'
  return m > 0 ? `${nonR}+${pts}` : `R+${pts}`
}
