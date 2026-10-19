import { useEffect, useRef, useState } from 'react'
import { parseSummary, type ParsedSummary } from '../data/parse'

export interface PollState {
  /** Newest valid summary seen so far; kept through failures. */
  summary: ParsedSummary | null
  /** Error from the most recent attempt, or null if it succeeded. */
  lastError: string | null
}

async function fetchSummary(url: string, timeoutMs: number): Promise<ParsedSummary> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    // no-cache = revalidate with the bucket each time (cheap 304s), rather than
    // trusting a copy the browser may have held for up to max-age.
    const res = await fetch(url, { cache: 'no-cache', signal: ctrl.signal })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return parseSummary(await res.json())
  } catch (e) {
    if (ctrl.signal.aborted) throw new Error('timed out', { cause: e })
    throw e
  } finally {
    clearTimeout(timer)
  }
}

/**
 * Polls summary.json forever, recovering on its own when the data comes back.
 * Never replaces a newer snapshot with an older one: a cache can briefly serve
 * the previous object after an overwrite, and going backwards in time on
 * election night would look like votes disappearing.
 */
export function useSummaryPoll(url: string, intervalMs: number, timeoutMs: number): PollState {
  const [state, setState] = useState<PollState>({ summary: null, lastError: null })
  const newest = useRef<number>(-Infinity)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let inFlight = false

    const tick = async () => {
      if (inFlight) return // one polling chain only, even if visibility fires mid-fetch
      inFlight = true
      clearTimeout(timer)
      try {
        const next = await fetchSummary(url, timeoutMs)
        if (cancelled) return
        const t = next.generatedAt.getTime()
        if (t >= newest.current) {
          newest.current = t
          setState({ summary: next, lastError: null })
        } else {
          setState((s) => ({ ...s, lastError: null }))
        }
      } catch (e) {
        if (cancelled) return
        const message = e instanceof Error ? e.message : String(e)
        setState((s) => ({ ...s, lastError: message }))
      }
      inFlight = false
      if (!cancelled) timer = setTimeout(tick, intervalMs)
    }

    // A backgrounded tab's timers get throttled; catch up as soon as it's visible.
    const onVisible = () => {
      if (document.visibilityState === 'visible') void tick()
    }

    void tick()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [url, intervalMs, timeoutMs])

  return state
}

/** Current time, re-read every `everyMs` so ages on screen keep counting. */
export function useNow(everyMs: number): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), everyMs)
    return () => clearInterval(id)
  }, [everyMs])
  return now
}
