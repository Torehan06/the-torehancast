/**
 * F4: is what's on screen current? Two independent failure modes, because the
 * page and the data live on different hosts (Firebase Hosting vs the GCS bucket):
 *
 *   stale   — fetches succeed but the newest snapshot is old (the poller stopped).
 *   failing — the last fetch failed (bucket unreachable, 5xx, bad JSON).
 *
 * Neither hides the last good numbers; both label them with their age.
 */

export type Freshness =
  | { kind: 'loading' }
  | { kind: 'unavailable'; error: string }
  | { kind: 'fresh'; ageS: number }
  | { kind: 'stale'; ageS: number }
  | { kind: 'failing'; ageS: number; error: string }

export interface FreshnessInput {
  /** generated_at of the newest summary we hold, or null if none yet. */
  generatedAt: Date | null
  /** Error from the most recent fetch, or null if it succeeded. */
  lastError: string | null
  now: Date
  staleAfterS: number
}

export function freshness({ generatedAt, lastError, now, staleAfterS }: FreshnessInput): Freshness {
  if (!generatedAt) return lastError ? { kind: 'unavailable', error: lastError } : { kind: 'loading' }
  // A visitor's clock running behind the publisher's would give a negative age.
  const ageS = Math.max(0, Math.floor((now.getTime() - generatedAt.getTime()) / 1000))
  if (lastError) return { kind: 'failing', ageS, error: lastError }
  return ageS > staleAfterS ? { kind: 'stale', ageS } : { kind: 'fresh', ageS }
}

export function formatAge(s: number): string {
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} min ${s % 60}s`
  const h = Math.floor(m / 60)
  return `${h} h ${m % 60} min`
}
