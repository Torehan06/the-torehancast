# Modeled and results-only races

Every published race, including `waiting` races, has a boolean `modeled`.
Existing `StateUpdate` inputs publish `modeled: true`; plurality and RCV
forecast fields retain their existing behavior and privacy gates.

Use `ResultsOnlyUpdate(state, race, candidates, votes, pct_reporting, as_of)`
for a race without a model. It requires no baseline, private prior, replay or
simulation. Candidate keys must match vote keys exactly and counts must be
nonnegative integers. Include every reported option, including independents.
`pct_reporting` is the official fraction of reporting units (0–1), or `None`
when unavailable. It must never be inferred from expected turnout.

A results-only race with positive votes publishes exactly these fields:

```json
{"state":"VA","race":"Senate","as_of":"2026-11-04T01:00:00Z",
 "modeled":false,"status":"live","candidates":{"D":"Dem","R":"Rep"},
 "votes":{"D":60,"R":40},"vote_share":{"D":0.6,"R":0.4},"pct_reporting":null}
```

Vote shares use all reported candidate votes as their denominator. No
probability, projected margin, expected vote count, model counting fraction,
RCV forecast or projected county table is emitted. This holds in live and
replay modes, including ME/AK, and under either publication gate. The model's
data-weight gate does not delay observed results-only counts.

Zero-vote results-only races publish only `state`, `race`, `as_of`, `modeled`
and `status: waiting`, even if the source reports precincts as complete. A
missing feed can be represented with zero counts and `pct_reporting=None`.

The public artifact checker requires `modeled` and rejects forecast fields
on results-only races, invalid counts, mismatched candidate keys and vote
shares inconsistent with counts. Regenerate historical replay artifacts to
include the flag before checking them. This is a schema migration; existing
privacy checks and live private-value coverage requirements still apply.

## Implementation decisions

- The approved M3 checklist is the implementation brief. Its new flag also
  extends waiting metadata; it is public registry information, never a prior.
- Results-only fields match the F-track contract (`votes`, `vote_share`,
  `pct_reporting`). Modeled candidate counts remain a separate integration
  concern: the current model result lacks unpooled observed candidate totals.
- Separate update types prevent results-only publishing from requiring a fake
  model or accidentally retaining probabilities. No feed or race is added here.
- Existing unit fixtures gain the flag; replay acceptance tests and all model
  thresholds are unchanged. Broader M3 prior-independence assurance is pending.

## Review follow-up

Independent review found no important issues. Deferred minor input-diagnostic
cleanup: non-dictionary candidates/votes can raise `AttributeError`, and an
extremely large integer reporting fraction can raise `OverflowError` rather
than `ValueError`. Both reject publication; adapters should supply the typed
input contract. Improving these diagnostics does not change forecast isolation.
