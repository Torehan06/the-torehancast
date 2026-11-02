/**
 * The public JSON contract between the publisher (src/torehancast/publish.py) and
 * this page. Every number the page shows comes from a field defined here.
 *
 * Files under data/<mode>/ (contract v2, PLAN.md W1):
 *   summary.json           — every Senate race, small; the page polls this.
 *   house.json             — every House race, same entry shapes.
 *   races/{race_id}.json   — one modeled race in detail (adds the county table).
 *   index.json             — replay only: the ordered list of frames.
 *
 * Every entry names its race: `race` is the canonical ID ("2026-NC-SEN",
 * "2026-NC-H01", "2026-AK-HAL"), `race_type` and `district` (null for Senate).
 * They're required in the strict schemas and optional in the loose ones, so
 * the deployed page keeps reading a poller that predates v2.
 *
 * Fields marked "M3" (`modeled`, reported `votes` / `vote_share`) are emitted by
 * the publisher for every live race. They stay optional here so older replay
 * output still parses; the page treats a missing `modeled` as "not modeled" and
 * so shows no probability for it. Modeled races leave `pct_reporting` out (the
 * model's `share_counted` covers progress); `vote_share` divides by every
 * reported vote, pooled "other" included.
 *
 * Schemas are built twice: loose (unknown fields stripped — what the page uses,
 * so a new publisher field never breaks the live site) and strict (unknown
 * fields rejected — what the fixture and drift tests use, so a renamed field
 * fails loudly instead of silently disappearing from the page).
 */
import { z } from 'zod'

export const RCV_STATUSES = ['awaiting_first_choices', 'awaiting_rcv', 'unresolved', 'resolved'] as const
export const RACE_TYPES = ['senate', 'senate-special', 'house'] as const
/** Canonical race ID, as src/torehancast/districts.py builds them. */
export const RACE_ID = /^\d{4}-[A-Z]{2}-(?:SEN|SEN-SPECIAL|H\d{2}|HAL)$/

function makeSchemas(strict: boolean) {
  const obj = strict ? z.strictObject : z.object

  const probability = z.number().min(0).max(1)
  const count = z.number().int().nonnegative()
  const candidateKey = z.string().min(1)
  /** Candidate key → display name, e.g. {"D": "Raphael Warnock (I) (Dem)"}. */
  const candidates = z.record(candidateKey, z.string())

  const identity = <T extends z.ZodType>(schema: T) => (strict ? schema : schema.optional())
  const base = {
    state: z.string().regex(/^[A-Z]{2}$/),
    race: strict ? z.string().regex(RACE_ID) : z.string(),
    race_type: identity(z.enum(RACE_TYPES)),
    /** District number for House races (1 for at-large seats); null for Senate. */
    district: identity(z.number().int().positive().nullable()),
    /** The feed's own timestamp for this race. Free text: replays use "T+1.25h". */
    as_of: z.string().nullable(),
  }

  /** M3: reported results, the same for modeled and results-only races. */
  const reported = {
    votes: z.record(candidateKey, count),
    vote_share: z.record(candidateKey, probability),
    /** Fraction of reporting units in; null when the feed doesn't say. */
    pct_reporting: probability.nullable(),
  }

  const waiting = obj({
    ...base,
    status: z.literal('waiting'),
    modeled: z.boolean().optional(),
  })

  const margin = obj({
    /** Non-R share minus R share of the two-party vote; positive = non-R ahead. */
    median: z.number(),
    p80: z.tuple([z.number(), z.number()]),
    p95: z.tuple([z.number(), z.number()]),
  })

  const county = obj({
    id: z.string(),
    status: z.string(),
    reported_votes: count,
    reported_margin: z.number().nullable(),
    counted_share: probability,
    expected_margin: z.number(),
  })

  const plurality = obj({
    ...base,
    status: z.literal('live'),
    modeled: z.boolean().optional(),
    candidates,
    p_win: z.record(candidateKey, probability),
    margin,
    /** Two-party votes counted so far. */
    reported_votes: count,
    expected_votes: count,
    /** Model's estimate of the share of the expected vote already counted. */
    share_counted: probability,
    counties: z.array(county).optional(),
    votes: reported.votes.optional(),
    vote_share: reported.vote_share.optional(),
    pct_reporting: reported.pct_reporting.optional(),
  })

  /** Maine and Alaska (docs/rcv.md). Null = not yet estimated; never guess. */
  const rcv = obj({
    ...base,
    status: z.literal('live'),
    modeled: z.boolean().optional(),
    candidates,
    rcv_status: z.enum(RCV_STATUSES),
    p_outright: z.record(candidateKey, probability.nullable()),
    p_via_rcv: z.record(candidateKey, probability.nullable()),
    p_win: z.record(candidateKey, probability.nullable()),
    p_no_rcv_needed: probability.nullable(),
    votes: reported.votes.optional(),
    vote_share: reported.vote_share.optional(),
    pct_reporting: reported.pct_reporting.optional(),
  })

  /** M3/F7: a race with reported votes and no model. Never carries a probability. */
  const resultsOnly = obj({
    ...base,
    status: z.literal('live'),
    modeled: z.literal(false),
    candidates,
    ...reported,
  })

  // Order matters: RCV is recognised by rcv_status, plurality by p_win + margin.
  const race = z.union([rcv, plurality, resultsOnly])

  const summary = obj({
    generated_at: z.iso.datetime({ offset: true }),
    mode: z.enum(['live', 'replay']),
    states: z.array(z.union([waiting, race])),
  })

  const house = obj({
    generated_at: z.iso.datetime({ offset: true }),
    mode: z.enum(['live', 'replay']),
    races: z.array(z.union([waiting, race])),
  })

  const replayIndex = obj({
    state: z.string(),
    pair: z.string(),
    order: z.string(),
    seed: z.number().int(),
    frames: z.array(obj({ time: z.number(), summary: z.string() })),
  })

  return { waiting, plurality, rcv, resultsOnly, race, anyRace: z.union([waiting, race]), summary, house, replayIndex }
}

export const loose = makeSchemas(false)
export const strict = makeSchemas(true)

export type WaitingRace = z.infer<typeof loose.waiting>
export type PluralityRace = z.infer<typeof loose.plurality>
export type RcvRace = z.infer<typeof loose.rcv>
export type ResultsOnlyRace = z.infer<typeof loose.resultsOnly>
export type LiveRace = PluralityRace | RcvRace | ResultsOnlyRace
export type Race = WaitingRace | LiveRace
export type Summary = z.infer<typeof loose.summary>
export type House = z.infer<typeof loose.house>
export type RaceType = (typeof RACE_TYPES)[number]
export type ReplayIndex = z.infer<typeof loose.replayIndex>
export type RcvStatus = (typeof RCV_STATUSES)[number]
