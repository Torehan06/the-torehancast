import { z } from 'zod'
import { loose, strict, type Race } from './contract'

export interface ParsedSummary {
  generatedAt: Date
  mode: 'live' | 'replay'
  /** Keyed by state postal code. */
  races: Map<string, Race>
  /** States whose entry didn't match the contract; shown as "data unavailable". */
  invalid: string[]
}

const envelope = z.object({
  generated_at: z.iso.datetime({ offset: true }),
  mode: z.enum(['live', 'replay']),
  states: z.array(z.unknown()),
})

/**
 * Parses summary.json for display. One bad race entry must not blank the whole
 * map on election night, so races are parsed one by one; only a broken envelope
 * (no timestamp, no list) throws, and the caller treats that as a failed fetch.
 */
export function parseSummary(raw: unknown): ParsedSummary {
  const env = envelope.parse(raw)
  const races = new Map<string, Race>()
  const invalid: string[] = []
  for (const entry of env.states) {
    const parsed = loose.anyRace.safeParse(entry)
    if (parsed.success) {
      races.set(parsed.data.state, parsed.data)
    } else {
      const state = (entry as { state?: unknown })?.state
      invalid.push(typeof state === 'string' ? state : '??')
    }
  }
  return { generatedAt: new Date(env.generated_at), mode: env.mode, races, invalid }
}

type Issue = z.core.$ZodIssue

/**
 * A race that matches no union branch only says "Invalid input". Report the
 * branch it came closest to instead, so the message names the actual field.
 */
function explain(issues: Issue[], prefix: PropertyKey[] = []): { path: PropertyKey[]; message: string }[] {
  return issues.flatMap((issue) => {
    const path = [...prefix, ...issue.path]
    if (issue.code === 'invalid_union' && issue.errors.length > 0) {
      const closest = issue.errors.reduce((a, b) => (b.length < a.length ? b : a))
      return explain(closest, path)
    }
    return [{ path, message: issue.message }]
  })
}

export type FileKind = 'summary' | 'detail' | 'index'

export function fileKind(name: string): FileKind | null {
  if (name === 'summary.json') return 'summary'
  if (name === 'index.json') return 'index'
  if (/^[A-Z]{2}\.json$/.test(name)) return 'detail'
  return null
}

/**
 * Validates one published file against the strict contract. Used by the fixture
 * test and by scripts/validate-json.ts (the Python drift test calls that).
 * `requireV1` additionally demands the M3 fields every race should carry.
 * Returns a list of human-readable problems; empty means valid.
 */
export function validatePublicFile(name: string, raw: unknown, requireV1 = false): string[] {
  const kind = fileKind(name)
  if (kind === null) return [`${name}: not a recognised public file name`]
  const schema = kind === 'summary' ? strict.summary : kind === 'index' ? strict.replayIndex : strict.anyRace
  const parsed = schema.safeParse(raw)
  if (!parsed.success) {
    return explain(parsed.error.issues).map((i) => `${name}: ${i.path.join('.') || '(root)'}: ${i.message}`)
  }
  if (!requireV1 || kind === 'index') return []
  const races = kind === 'summary' ? (parsed.data as { states: Race[] }).states : [parsed.data as Race]
  const problems: string[] = []
  // Waiting entries stay exactly {state, race, as_of, status}: that minimal shape
  // is the publisher's privacy guarantee (tests/unit/test_publish.py).
  for (const r of races.filter((r) => r.status === 'live')) {
    if (r.modeled === undefined) problems.push(`${name}: ${r.state}: missing "modeled" (M3)`)
    if (!('votes' in r && r.votes)) problems.push(`${name}: ${r.state}: missing "votes" (M3)`)
  }
  return problems
}
