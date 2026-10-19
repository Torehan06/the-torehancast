/**
 * Build-time settings (Vite env vars). The data URL is fixed at build time on
 * purpose: no query-string override, so nobody can link to this page with
 * someone else's JSON behind it.
 *
 *   VITE_DATA_BASE     where summary.json lives, ending in "/".
 *                      Default "data/replay/" (same origin; dev serves fixtures).
 *                      Production: https://storage.googleapis.com/<bucket>/data/live/
 *   VITE_POLL_MS       how often to fetch summary.json (default 20000, the bucket's max-age).
 *   VITE_STALE_AFTER_S snapshot age that triggers the stale banner (default 120).
 */

function num(value: string | undefined, fallback: number): number {
  const n = Number(value)
  return value !== undefined && value !== '' && Number.isFinite(n) && n > 0 ? n : fallback
}

const env = import.meta.env

export const DATA_BASE: string = env.VITE_DATA_BASE || 'data/replay/'
export const SUMMARY_URL = new URL('summary.json', new URL(DATA_BASE, window.location.href)).toString()
export const POLL_MS = num(env.VITE_POLL_MS, 20_000)
export const STALE_AFTER_S = num(env.VITE_STALE_AFTER_S, 120)
export const FETCH_TIMEOUT_MS = 10_000
