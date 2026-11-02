import { useCallback, useEffect, useRef, useState } from 'react'
import { FETCH_TIMEOUT_MS, HOUSE_URL, POLL_MS, STALE_AFTER_S, SUMMARY_URL } from './config'
import { formatAge, freshness, pollForView } from './data/freshness'
import { parseHouse, parseSummary, type ParsedHouse, type ParsedSummary } from './data/parse'
import { parseRoute, routeHash, type Route, type View } from './data/route'
import { SENATE_RACES_2026, SWING_SEATS } from './data/states'
import { useNow, usePoll, type PollState } from './hooks/usePoll'
import { ChamberToggle } from './components/ChamberToggle'
import { DistrictPanel } from './components/DistrictPanel'
import { HouseLists } from './components/HouseLists'
import { HouseTiles } from './components/HouseTiles'
import { Legend } from './components/Legend'
import { SwingSeats } from './components/SwingSeats'
import { ThemeToggle } from './components/ThemeToggle'
import { RaceList } from './components/RaceList'
import { RacePanel } from './components/RacePanel'
import { SenateMap } from './components/SenateMap'
import { StatusBanner } from './components/StatusBanner'

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash))
  const { view, selected } = route
  const otherRaceCount = SENATE_RACES_2026.filter(({ state }) => !SWING_SEATS.has(state.code)).length
  const summaryPoll = usePoll(SUMMARY_URL, parseSummary, POLL_MS, FETCH_TIMEOUT_MS)
  // house.json is only fetched for the House view, which holds the only panel that reads it.
  const housePoll = usePoll(HOUSE_URL, parseHouse, POLL_MS, FETCH_TIMEOUT_MS, { enabled: view === 'house', missingOk: true })
  const summary = summaryPoll.data
  const house = housePoll.data
  const now = useNow(1000)
  const source = pollForView<PollState<ParsedSummary | ParsedHouse>>(view, summaryPoll, housePoll)
  const status = freshness({ generatedAt: source.data?.generatedAt ?? null, lastError: source.lastError, now, staleAfterS: STALE_AFTER_S })
  const invoker = useRef<HTMLOrSVGElement | null>(null)

  // #GA selects Georgia, #NC-01 a House district, so a race can be linked to directly.
  useEffect(() => {
    const onHash = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const go = useCallback((next: Route) => {
    setRoute(next)
    const hash = routeHash(next)
    history.replaceState(null, '', hash ? `#${hash}` : window.location.pathname + window.location.search)
  }, [])

  const select = useCallback(
    (code: string | null) => {
      go({ view, selected: code })
      if (code) {
        invoker.current = document.activeElement as HTMLOrSVGElement | null
        requestAnimationFrame(() => document.getElementById('panel-title')?.focus())
      } else {
        // Back to the tile or row that opened the panel.
        requestAnimationFrame(() => invoker.current?.focus())
      }
    },
    [go, view],
  )

  const changeView = useCallback((next: View) => go({ view: next, selected: null }), [go])

  return (
    <div className="page">
      <header className="masthead">
        <h1 className="wordmark">
          <span className="wordmark__oval" aria-hidden="true" />
          The TörehanCast
        </h1>
        <ThemeToggle />
        <p className="masthead__sub">Live results and win chances for the 2026 Senate and House races, from official state counts.</p>
        <p className="masthead__status" data-testid="freshness" aria-live="polite">
          {status.kind === 'loading' && 'Loading results…'}
          {(status.kind === 'fresh' || status.kind === 'stale' || status.kind === 'failing') &&
            `Updated ${formatAge(status.ageS)} ago`}
        </p>
      </header>

      <StatusBanner status={status} mode={source.data?.mode ?? null} />

      <ChamberToggle view={view} onChange={changeView} />

      {view === 'senate' ? (
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
            <SwingSeats summary={summary} selected={selected} onSelect={select} />
            <h2 className="list-title">Other {otherRaceCount} races</h2>
            <RaceList summary={summary} selected={selected} onSelect={select} />
          </div>
        </main>
      ) : (
        <main className="layout">
          <div className="layout__map tiles">
            <HouseTiles house={house} selected={selected} onSelect={select} />
            <Legend chamber="house" />
          </div>
          <aside className="layout__side">
            {selected ? (
              <DistrictPanel districtKey={selected} house={house} onClose={() => select(null)} />
            ) : (
              <p className="hint">Pick a district on the map or browse by state below to see its votes and, for modeled races, each candidate’s chance of winning.</p>
            )}
          </aside>
          <div className="layout__list">
            <HouseLists house={house} selected={selected} onSelect={select} />
          </div>
        </main>
      )}

      <footer className="footer">
        Results from official state election websites. Probabilities come from the TörehanCast model and are shown only
        for modeled races; other races show reported votes with no forecast.{' '}
        <a href="https://github.com/Torehan06/the-torehancast">Method and source code</a>.
      </footer>
    </div>
  )
}
