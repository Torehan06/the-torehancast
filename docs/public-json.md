# Public JSON

## Files and race identity (contract v2, Oct 21)

Under `data/{mode}/`:

| File | Holds |
|---|---|
| `summary.json` | `{generated_at, mode, states: [...]}`: every Senate race (regular and special). The page polls this. |
| `house.json` | `{generated_at, mode, races: [...]}`: every House race, same entry shapes. |
| `races/{race_id}.json` | One modeled race in detail (adds the county table). Results-only races have none. |
| `index.json` | Replay only: the ordered frames. |

The per-state `{state}.json` files are gone: a state with a Senate race and House
districts has many races, and one file per state let the second overwrite the first.

Every entry carries `race`, the canonical ID from `src/torehancast/districts.py`
(`2026-NC-SEN`, `2026-FL-SEN-SPECIAL`, `2026-NC-H01`, `2026-AK-HAL`), plus `race_type`
(`senate`, `senate-special`, `house`) and `district` (the House district number, 1 for
at-large, null for Senate). The publisher and the checker both reject an entry whose
ID, type, district and state disagree. Replays publish under the ID of the live race
they rehearse.

A race is published as ranked-choice (`rcv_status`, no plurality probabilities) when
its config sets `ranked_choice`, which `config.py` requires for every ME and AK federal
race; until its RCV draws exist it fails closed to `awaiting_first_choices`.

A cycle with no Senate (or no House) updates leaves that file as it was: an empty list
is invalid, and the page keeps showing the last good one.

# Modeled and results-only races

Every published race, including `waiting` races, has a boolean `modeled`.
Existing `StateUpdate` inputs publish `modeled: true`; plurality and RCV
forecast fields retain their existing behavior and privacy gates.

Use `ResultsOnlyUpdate(state, race, candidates, votes, pct_reporting, as_of,
race_type=..., district=...)` for a race without a model. It requires no baseline, private prior, replay or
simulation. Candidate keys must match vote keys exactly and counts must be
nonnegative integers. Include every reported option, including independents.
`pct_reporting` is the official fraction of reporting units (0–1), or `None`
when unavailable. It must never be inferred from expected turnout.

A results-only race with positive votes publishes exactly these fields:

```json
{"state":"VA","race":"2026-VA-SEN","race_type":"senate","district":null,
 "as_of":"2026-11-04T01:00:00Z","modeled":false,"status":"live","candidates":{"D":"Dem","R":"Rep"},
 "votes":{"D":60,"R":40},"vote_share":{"D":0.6,"R":0.4},"pct_reporting":null}
```

Vote shares use all reported candidate votes as their denominator. No
probability, projected margin, expected vote count, model counting fraction,
RCV forecast or projected county table is emitted. This holds in live and
replay modes, including ME/AK, and under either publication gate. The model's
data-weight gate does not delay observed results-only counts.

Zero-vote results-only races publish only `state`, `race`, `race_type`,
`district`, `as_of`, `modeled` and `status: waiting`, even if the source reports precincts as complete. A
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
private prior, matched by its canonical race ID. Results-only races need no
per-race prior. The private priors file is gitignored.

The checker allows only JSON artifacts in the supplied **public data** tree.
It rejects config/YAML, symlinks, file names outside the v2 layout, invalid
payloads, private keys, and copies of private values. Paths and contents are
withheld from failure messages. This is conservative detection of accidental
copies, not a proof against arbitrary encoding or deliberate exfiltration.

What counts as a copy (Törehan's decision, Oct 21; the release gate):

- **Numbers inside a race entry** are compared with that race's own prior values
  that have 4+ decimals, and their 3- and 4-place roundings that keep 4+ decimals.
  Hand-entered priors have 1-3 decimals, and on a full night thousands of published
  probabilities, margins and county shares equal such values by chance: simulated
  76-prior nights raised a false alarm about 100% of the time when every number was
  compared (80% even without county tables). A copied `0.1` can't be told from a
  chance `0.1`, so the check looks only where a match means a copy. The canary
  tests (7-decimal priors through the real publisher) prove the code never copies one.
- **Text** (candidate names, timestamps, county IDs, file names) is compared with
  every non-integer prior value, including numbers embedded in it.
- **Numbers outside race entries** (envelopes, the replay index) are compared with
  every prior value and its roundings.
- Never scanned, because they can't carry a prior: the identity fields once shown to
  agree, raw vote counts, and `vote_share` equal to the share recomputed from them.

`tests/unit/test_public_json_v2.py` publishes all 470 races with 76 hand-style
priors and checks that the night passes, that a prior written into text is caught,
and that a precise prior copied into a margin is caught.

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
