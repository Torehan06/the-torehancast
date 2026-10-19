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
  thresholds are unchanged. Private-input verification is described below.

## Review follow-up

Independent review found no important issues. Deferred minor input-diagnostic
cleanup: non-dictionary candidates/votes can raise `AttributeError`, and an
extremely large integer reporting fraction can raise `OverflowError` rather
than `ValueError`. Both reject publication; adapters should supply the typed
input contract. Improving these diagnostics does not change forecast isolation.

## Private-input verification

The privacy contract, clarified by Törehan on October 19, preserves Bayesian
forecasts. Private hand-entered priors and config must not be copied into public
artifacts. A posterior may depend on priors after the live release gate opens;
posterior independence is not the requirement. Waiting output contains only
public identity/timestamp/status/modeled metadata under both release gates.

Run the local verification suite (synthetic canaries, no real priors needed):

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_live_privacy.py tests/unit/test_privacy_verification.py
```

It exercises the real model, live publisher, written summary/detail JSON and
checker with two intentionally distinctive synthetic prior sets, including
GA and the ME/AK RCV paths, no votes, thin data, both release gates and final
counts. Each scan is also mutation-tested with an embedded private numeric
copy. These fixtures are never presented as actual live private-file coverage.

Before releasing any live data directory, run the strict artifact check with
the **actual** private config file outside the public tree:

```sh
python scripts/check_public_json.py out/ --mode live --priors /private/config/priors.yaml
```

The default command requires private coverage, using `config/priors.yaml` if
`--priors` is omitted. Missing, empty, all-unset, duplicate-key or malformed
private files fail closed. Each live modeled race needs a matching non-null
private prior; canonical race IDs match exactly. Legacy display labels work
only when the state has a single unambiguous configured prior. Results-only
races need no per-race prior. The private priors file is gitignored.

The checker allows only JSON artifacts in the supplied **public data** tree.
It rejects config/YAML, symlinks, other file types, invalid payloads, private
keys and exact/common-rounded numeric copies in keys, values, embedded strings
and relative filenames (including scientific notation). Paths and contents
are withheld from failure messages. Common numeric values can collide with
legitimate public data: a match requires investigation, never automatic bypass.
This is conservative detection of accidental copies, not a proof against
arbitrary encoding or deliberate exfiltration.

For replay shape checks without private config, opt in explicitly:

```sh
python scripts/check_public_json.py out/ --structure-only
```

It prints `STRUCTURE ONLY` and never a privacy pass. Live paths, live summary
metadata and `--mode live` still require private coverage; the structure-only
option cannot bypass that requirement. Use `--mode live` for flat exports whose
paths do not identify their mode. Scan JSON separately from the frontend build;
HTML/JS files intentionally fail this data-only checker.

Actual private-file verification and hosted access checks require the actual
private config and approved hosting resources. Neither exists in this local
checkpoint, so those checks must run at release time. The canary tests and
strict missing-config failure are verified locally.
