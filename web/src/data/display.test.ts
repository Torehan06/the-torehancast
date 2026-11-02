import { describe, expect, it } from 'vitest'
import type { PluralityRace, Race, RcvRace, ResultsOnlyRace } from './contract'
import { formatMargin, formatProbability, leader, showsProbabilities, voteState } from './display'

const base = { state: 'GA', race: '2026-GA-SEN', race_type: 'senate', district: null, as_of: null } as const

const modeled: PluralityRace = {
  ...base,
  status: 'live',
  modeled: true,
  candidates: { D: 'Dem', R: 'Rep' },
  p_win: { D: 0.8, R: 0.2 },
  margin: { median: 0.02, p80: [0, 0.04], p95: [-0.01, 0.05] },
  reported_votes: 1000,
  expected_votes: 4000,
  share_counted: 0.25,
  votes: { D: 520, R: 480 },
  vote_share: { D: 0.52, R: 0.48 },
  pct_reporting: 0.3,
}

const resultsOnly: ResultsOnlyRace = {
  ...base,
  state: 'IL',
  status: 'live',
  modeled: false,
  candidates: { D: 'Dem', R: 'Rep' },
  votes: { D: 400, R: 600 },
  vote_share: { D: 0.4, R: 0.6 },
  pct_reporting: null,
}

const rcvNull: RcvRace = {
  ...base,
  state: 'AK',
  status: 'live',
  modeled: true,
  candidates: { D: 'Dem', R: 'Rep', I: 'Ind' },
  rcv_status: 'awaiting_first_choices',
  p_outright: { D: null, R: null, I: null },
  p_via_rcv: { D: null, R: null, I: null },
  p_win: { D: null, R: null, I: null },
  p_no_rcv_needed: null,
}

describe('showsProbabilities', () => {
  it('needs an explicit modeled: true', () => {
    expect(showsProbabilities(modeled)).toBe(true)
    expect(showsProbabilities({ ...modeled, modeled: undefined })).toBe(false)
    expect(showsProbabilities({ ...modeled, modeled: false })).toBe(false)
    expect(showsProbabilities(resultsOnly)).toBe(false)
  })

  it('never shows a zero-vote probability, even if the publisher sent one', () => {
    const zero: PluralityRace = { ...modeled, reported_votes: 0, votes: { D: 0, R: 0 } }
    expect(showsProbabilities(zero)).toBe(false)
    const legacyZero: Race = { ...modeled, reported_votes: 0, votes: undefined }
    expect(showsProbabilities(legacyZero)).toBe(false)
  })

  it('is false for waiting and missing races', () => {
    expect(showsProbabilities({ ...base, status: 'waiting', modeled: true })).toBe(false)
    expect(showsProbabilities(undefined)).toBe(false)
  })
})

describe('voteState', () => {
  it('distinguishes none, some and unknown', () => {
    expect(voteState(undefined)).toBe('none')
    expect(voteState({ ...base, status: 'waiting' })).toBe('none')
    expect(voteState(modeled)).toBe('some')
    expect(voteState({ ...resultsOnly, votes: { D: 0, R: 0 } })).toBe('none')
    expect(voteState(rcvNull)).toBe('unknown')
  })
})

describe('leader', () => {
  it('uses win probability for modeled races, with strength tiers', () => {
    expect(leader(modeled)).toMatchObject({ key: 'D', basis: 'probability', value: 0.8, strength: 'medium' })
    expect(leader({ ...modeled, p_win: { D: 0.03, R: 0.97 } })).toMatchObject({ key: 'R', strength: 'strong' })
    expect(leader({ ...modeled, p_win: { D: 0.6, R: 0.4 } })).toMatchObject({ strength: 'light' })
  })

  it('uses vote share, always lightest, for results-only races', () => {
    expect(leader(resultsOnly)).toMatchObject({ key: 'R', basis: 'vote_share', value: 0.6, strength: 'light' })
  })

  it('falls back to the vote lead while RCV probabilities are null', () => {
    const withVotes: RcvRace = { ...rcvNull, votes: { D: 5, R: 3, I: 1 }, vote_share: { D: 0.56, R: 0.33, I: 0.11 } }
    expect(leader(withVotes)).toMatchObject({ key: 'D', basis: 'vote_share' })
    expect(leader(rcvNull)).toBeNull()
  })

  it('returns null on a tie', () => {
    expect(leader({ ...resultsOnly, vote_share: { D: 0.5, R: 0.5 } })).toBeNull()
  })
})

describe('formatting', () => {
  it('never prints 0% or 100% for a probability', () => {
    expect(formatProbability(1)).toBe('>99%')
    expect(formatProbability(0)).toBe('<1%')
    expect(formatProbability(0.874)).toBe('87%')
    expect(formatProbability(null)).toBe('not yet estimated')
  })

  it('labels the margin by side', () => {
    expect(formatMargin(0.0168, 'D')).toBe('D+1.7')
    expect(formatMargin(-0.071, 'D')).toBe('R+7.1')
    expect(formatMargin(0.0004, 'I')).toBe('Even')
  })
})
