import type { LiveRace, PluralityRace, RcvRace, RcvStatus } from '../data/contract'
import {
  formatCount,
  formatMargin,
  formatProbability,
  formatShare,
  isPlurality,
  isRcv,
  NO_VOTES,
  showsProbabilities,
  voteState,
} from '../data/display'
import type { ParsedSummary } from '../data/parse'
import { SENATE_RACES_2026, type UsState } from '../data/states'

interface Props {
  code: string
  summary: ParsedSummary | null
  onClose: () => void
}

export function RacePanel({ code, summary, onClose }: Props) {
  const entry = SENATE_RACES_2026.find((r) => r.state.code === code)
  if (!entry) return null
  const race = summary?.races.get(code)
  const invalid = summary?.invalid.includes(code) ?? false
  const votes = voteState(race)

  return (
    <section className="panel" aria-labelledby="panel-title" data-testid="race-panel">
      <header className="panel__head">
        <h2 id="panel-title" tabIndex={-1}>
          <span className="panel__state">{entry.state.name}</span>
          <span className="panel__race">U.S. Senate{entry.special ? ' special election' : ''}</span>
        </h2>
        <button type="button" className="panel__close" onClick={onClose} aria-label="Close race details">
          ×
        </button>
      </header>

      {invalid ? (
        <p className="panel__empty">Data for this race is unavailable right now.</p>
      ) : votes === 'none' || !race || race.status === 'waiting' ? (
        <p className="panel__empty" data-testid="no-votes">
          {NO_VOTES}
        </p>
      ) : (
        <LiveBody race={race} />
      )}

      <Timestamps state={entry.state} summary={summary} asOf={race?.as_of ?? null} />
    </section>
  )
}

function LiveBody({ race }: { race: LiveRace }) {
  return (
    <>
      <Results race={race} />
      {showsProbabilities(race) ? (
        isRcv(race) ? <RcvProbabilities race={race} /> : <PluralityProbabilities race={race as PluralityRace} />
      ) : (
        <p className="panel__note" data-testid="no-forecast">
          {race.modeled === false
            ? 'Reported votes only — no forecast for this race.'
            : 'This data isn’t marked as modeled, so no probability is shown.'}
        </p>
      )}
    </>
  )
}

function Results({ race }: { race: LiveRace }) {
  const keys = Object.keys(race.candidates)
  if (race.votes) {
    const votes = race.votes
    const sorted = [...keys].sort((a, b) => (votes[b] ?? 0) - (votes[a] ?? 0))
    return (
      <div data-testid="results">
        <table className="results">
          <thead>
            <tr>
              <th scope="col">Candidate</th>
              <th scope="col">Votes</th>
              <th scope="col">Share</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((k) => (
              <tr key={k}>
                <th scope="row">{race.candidates[k]}</th>
                <td>{votes[k] !== undefined ? formatCount(votes[k]) : '—'}</td>
                <td>{race.vote_share?.[k] !== undefined ? formatShare(race.vote_share[k]) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {race.pct_reporting !== undefined && (
          <p className="panel__meta" data-testid="pct-reporting">
            {race.pct_reporting === null ? 'Reporting progress not published by this state' : `${formatShare(race.pct_reporting)} reporting`}
          </p>
        )}
      </div>
    )
  }
  // Pre-M3 payloads: names and the two-party count, but no per-candidate votes.
  return (
    <div data-testid="results">
      <ul className="candidates">
        {keys.map((k) => (
          <li key={k}>{race.candidates[k]}</li>
        ))}
      </ul>
      {isPlurality(race) && (
        <p className="panel__meta">
          {formatCount(race.reported_votes)} two-party votes counted · per-candidate counts not yet published
        </p>
      )}
    </div>
  )
}

function PluralityProbabilities({ race }: { race: PluralityRace }) {
  const keys = Object.keys(race.p_win).sort((a, b) => race.p_win[b] - race.p_win[a])
  const nonR = Object.keys(race.candidates).filter((k) => k !== 'R')
  const showMargin = nonR.length === 1 && 'R' in race.candidates
  return (
    <div className="forecast" data-testid="probabilities">
      <h3>Chance of winning</h3>
      <p className="forecast__explain">
        The model's probability that each candidate wins the race. These are not projected vote shares.
      </p>
      <ul className="prob-bars">
        {keys.map((k) => (
          <li key={k} className={`lead-${k === 'D' || k === 'R' ? k : 'other'}`}>
            <span className="prob-bars__name">{race.candidates[k] ?? k}</span>
            <span className="prob-bars__value">{formatProbability(race.p_win[k])}</span>
            <span className="prob-bars__track" aria-hidden="true">
              <span className="prob-bars__fill" style={{ width: `${race.p_win[k] * 100}%` }} />
            </span>
          </li>
        ))}
      </ul>
      {showMargin && (
        <p className="panel__meta" data-testid="margin">
          Projected two-party margin {formatMargin(race.margin.median, nonR[0])} (80% range{' '}
          {formatMargin(race.margin.p80[0], nonR[0])} to {formatMargin(race.margin.p80[1], nonR[0])}). About{' '}
          {formatShare(race.share_counted)} of the expected vote counted.
        </p>
      )}
    </div>
  )
}

const RCV_STATUS_TEXT: Record<RcvStatus, string> = {
  awaiting_first_choices: 'Waiting for enough first-choice results to estimate anything.',
  awaiting_rcv: 'A ranked-choice count looks possible, and its outcome can’t be estimated yet.',
  unresolved: 'The ranked-choice outcome is too close to call in some simulations.',
  resolved: 'Estimates include the ranked-choice count.',
}

function RcvProbabilities({ race }: { race: RcvRace }) {
  const keys = Object.keys(race.candidates)
  const anyNull = [race.p_outright, race.p_via_rcv, race.p_win].some((m) => keys.some((k) => m[k] == null))
  return (
    <div className="forecast" data-testid="probabilities">
      <h3>Chance of winning (ranked-choice race)</h3>
      <p className="forecast__explain">
        Probabilities of winning, not vote shares. A candidate wins outright with more than half of first choices;
        otherwise the ranked-choice count decides. “Wins overall” is the sum of the two.
      </p>
      <p className="panel__meta" data-testid="rcv-status">
        {RCV_STATUS_TEXT[race.rcv_status]}
      </p>
      <table className="results">
        <thead>
          <tr>
            <th scope="col">Candidate</th>
            <th scope="col">Wins outright</th>
            <th scope="col">Wins via RCV</th>
            <th scope="col">Wins overall</th>
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k}>
              <th scope="row">{race.candidates[k]}</th>
              <ProbCell p={race.p_outright[k]} />
              <ProbCell p={race.p_via_rcv[k]} />
              <ProbCell p={race.p_win[k]} />
            </tr>
          ))}
        </tbody>
      </table>
      {anyNull && <p className="panel__meta">— not yet estimated</p>}
      <p className="panel__meta" data-testid="p-no-rcv">
        Chance no ranked-choice count is needed: {formatProbability(race.p_no_rcv_needed)}
      </p>
    </div>
  )
}

function ProbCell({ p }: { p: number | null | undefined }) {
  if (p === null || p === undefined) {
    return (
      <td>
        <span aria-label="not yet estimated" title="not yet estimated">
          —
        </span>
      </td>
    )
  }
  return <td>{formatProbability(p)}</td>
}

function Timestamps({ state, summary, asOf }: { state: UsState; summary: ParsedSummary | null; asOf: string | null }) {
  if (!summary) return null
  return (
    <p className="panel__time" data-testid="snapshot-time">
      Snapshot taken <time dateTime={summary.generatedAt.toISOString()}>{formatTime(summary.generatedAt)}</time>
      {asOf && (
        <>
          <br />
          {state.name} feed time {asOf}
        </>
      )}
    </p>
  )
}

function formatTime(d: Date): string {
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    timeZoneName: 'short',
  })
}
