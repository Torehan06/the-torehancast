import { formatAge, type Freshness } from '../data/freshness'

/**
 * F4. Loud on purpose: on election night a frozen page that looks live is the
 * worst failure, worse than an error. The last numbers stay on screen below.
 */
export function StatusBanner({ status, mode }: { status: Freshness; mode: 'live' | 'replay' | null }) {
  return (
    <>
      {mode === 'replay' && (
        <div className="banner banner--replay" data-testid="replay-banner">
          Replay or test data — these are not 2026 results.
        </div>
      )}
      {status.kind === 'stale' && (
        <div className="banner banner--stale" role="alert" data-testid="stale-banner">
          <strong>Results may be out of date.</strong> The newest data is {formatAge(status.ageS)} old. Numbers below
          are the last ones received.
        </div>
      )}
      {status.kind === 'failing' && (
        <div className="banner banner--failing" role="alert" data-testid="failing-banner">
          <strong>Can’t reach the results data</strong> ({status.error}). Retrying automatically. Numbers below are{' '}
          {formatAge(status.ageS)} old.
        </div>
      )}
      {status.kind === 'unavailable' && (
        <div className="banner banner--failing" role="alert" data-testid="failing-banner">
          <strong>Can’t reach the results data</strong> ({status.error}). Retrying automatically.
        </div>
      )}
    </>
  )
}
