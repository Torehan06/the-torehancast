import { useCallback, useEffect, useState } from 'react'
import { FETCH_TIMEOUT_MS, POLL_MS, STALE_AFTER_S, SUMMARY_URL } from './config'
import { formatAge, freshness } from './data/freshness'
import { HAS_SENATE_RACE } from './data/states'
import { useNow, useSummaryPoll } from './hooks/useSummaryPoll'
import { Legend } from './components/Legend'
import { RaceList } from './components/RaceList'
import { RacePanel } from './components/RacePanel'
import { SenateMap } from './components/SenateMap'
import { StatusBanner } from './components/StatusBanner'

function stateFromHash(): string | null {
  const code = window.location.hash.slice(1).toUpperCase()
  return HAS_SENATE_RACE.has(code) ? code : null
}

export default function App() {
  const { summary, lastError } = useSummaryPoll(SUMMARY_URL, POLL_MS, FETCH_TIMEOUT_MS)
  const now = useNow(1000)
  const status = freshness({ generatedAt: summary?.generatedAt ?? null, lastError, now, staleAfterS: STALE_AFTER_S })
  const [selected, setSelected] = useState<string | null>(stateFromHash)

  // #GA in the URL selects Georgia, so a race can be linked to directly.
  useEffect(() => {
    const onHash = () => setSelected(stateFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const select = useCallback((code: string | null) => {
    setSelected(code)
    history.replaceState(null, '', code ? `#${code}` : window.location.pathname + window.location.search)
    if (code) requestAnimationFrame(() => document.getElementById('panel-title')?.focus())
  }, [])

  return (
    <div className="page">
      <header className="masthead">
        <h1 className="wordmark">
          <span className="wordmark__oval" aria-hidden="true" />
          The Torehancast
        </h1>
        <p className="masthead__sub">Live results and win chances for the 2026 Senate races, from official state counts.</p>
        <p className="masthead__status" data-testid="freshness" aria-live="polite">
          {status.kind === 'loading' && 'Loading results…'}
          {(status.kind === 'fresh' || status.kind === 'stale' || status.kind === 'failing') &&
            `Updated ${formatAge(status.ageS)} ago`}
        </p>
      </header>

      <StatusBanner status={status} mode={summary?.mode ?? null} />

      <main className="layout">
        <div className="layout__map">
          <SenateMap summary={summary} selected={selected} onSelect={select} />
          <Legend />
        </div>
        <aside className="layout__side">
          {selected ? (
            <RacePanel code={selected} summary={summary} onClose={() => select(null)} />
          ) : (
            <p className="hint">Pick a state on the map or in the list below to see its votes and, for modeled races, each candidate’s chance of winning.</p>
          )}
        </aside>
        <div className="layout__list">
          <h2 className="list-title">All 35 races</h2>
          <RaceList summary={summary} selected={selected} onSelect={select} />
        </div>
      </main>

      <footer className="footer">
        Results from official state election websites. Probabilities come from the Torehancast model and are shown only
        for modeled races; other races show reported votes with no forecast.{' '}
        <a href="https://github.com/Torehan06/the-torehancast">Method and source code</a>.
      </footer>
    </div>
  )
}
