import { useEffect, useRef, useState } from 'react'

export interface PollState<T> {
  /** Newest valid snapshot seen so far; kept through failures. */
  data: T | null
  /** Error from the most recent attempt, or null if it succeeded. */
  lastError: string | null
  /** False until an attempt finishes after (re)starting, so an old snapshot isn't judged before it can refresh. */
  settled: boolean
}

export interface PollOptions {
  /** False stops the polling chain; the last snapshot stays in state. */
  enabled?: boolean
  /** A 404 means "not published yet": no snapshot and no error. */
  missingOk?: boolean
}

async function fetchSnapshot<T>(url: string, parse: (raw: unknown) => T, timeoutMs: number, missingOk: boolean): Promise<T | null> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    // no-cache = revalidate with the bucket each time (cheap 304s), rather than
    // trusting a copy the browser may have held for up to max-age.
    const res = await fetch(url, { cache: 'no-cache', signal: ctrl.signal })
    if (missingOk && res.status === 404) return null
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return parse(await res.json())
  } catch (e) {
    if (ctrl.signal.aborted) throw new Error('timed out', { cause: e })
    throw e
  } finally {
    clearTimeout(timer)
  }
}

/**
 * Polls a published JSON file, recovering on its own when the data comes back.
 * Never replaces a newer snapshot with an older one: a cache can briefly serve
 * the previous object after an overwrite, and going backwards in time on
 * election night would look like votes disappearing.
 *
 * `parse` must be stable (a module-level function): a new one restarts the poll.
 */
export function usePoll<T extends { generatedAt: Date }>(
  url: string,
  parse: (raw: unknown) => T,
  intervalMs: number,
  timeoutMs: number,
  { enabled = true, missingOk = false }: PollOptions = {},
): PollState<T> {
  const [state, setState] = useState<PollState<T>>({ data: null, lastError: null, settled: false })
  const newest = useRef<number>(-Infinity)

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let inFlight = false

    const tick = async () => {
      if (inFlight) return // one polling chain only, even if visibility fires mid-fetch
      inFlight = true
      clearTimeout(timer)
      try {
        const next = await fetchSnapshot(url, parse, timeoutMs, missingOk)
        if (cancelled) return
        const t = next?.generatedAt.getTime() ?? -Infinity
        if (next && t >= newest.current) {
          newest.current = t
          setState({ data: next, lastError: null, settled: true })
        } else {
          setState((s) => ({ ...s, lastError: null, settled: true }))
        }
      } catch (e) {
        if (cancelled) return
        const message = e instanceof Error ? e.message : String(e)
        setState((s) => ({ ...s, lastError: message, settled: true }))
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
      setState((s) => ({ ...s, lastError: null, settled: false }))
    }
  }, [url, parse, intervalMs, timeoutMs, enabled, missingOk])

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
