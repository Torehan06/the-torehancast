# Georgia native-feed replay

From the repo root, with the project environment active:

```sh
python -m torehancast.replay.e2e --state GA --out out/
python scripts/check_public_json.py out/
```

Use a fresh output directory for each run. Existing replay output is refused to
avoid mixing frames from different elections. Nothing is uploaded or deployed.
The command uses the locally archived official county files, existing baselines,
and historical replay configuration. It never reads live private priors or fetches
results over the network. Missing archives fail rather than trigger a download.

County documents must have unique identities matching the baseline county set;
incomplete or duplicate archives fail before any publication.

The primary pair is 2020 Senate → 2022 Senate. To run the secondary 2022 Senate →
2024 presidential pair, use `--pair secondary --out out/secondary/`. Other options
are `--order`, `--seed`, and `--draws` (4,000 by default).

## Pipeline

Each synthetic 15-minute poll interval is rendered into copies of the archived
Enhanced Voting county JSON documents. The renderer updates option/group totals,
precinct fractions, timestamps and per-vote-type reporting statuses. Unreported
groups have zero votes and explicit not-reported status; partial groups do not
inherit an archive's final completion state. Precinct denominators represent the
synthetic chunks, not the county's original precinct count.

The documents then cross a JSON serialization boundary and pass through the same
`snapshot_from_docs` adapter used for official files, before `RaceModel.run` and
`publish.publish`. No synthetic cells bypass the adapter on their way to the model.

The model pools minor candidates under `other`. To render those synthetic arrivals
back to individual ballot options, the renderer apportions votes by archived
county/vote-type weights with integer remainders. Intermediate option counts are
synthetic; the final frame recovers each option's original archived counts.

## Files

All public artifacts are under `data/replay/`:

- `summary.json` and `GA.json`: latest published results (final after completion).
- `frames/000000/summary.json` and `frames/000000/GA.json`, etc.: successive polls.
- `index.json`: replay metadata and ordered frame times/summary paths, relative to
  `data/replay/`, for playback by the dashboard.

Race and candidate labels refer to the historical target election. The initial
replay frame intentionally shows the historical replay model before votes arrive;
the existing live waiting gate remains unchanged. Native county documents stay
in memory; raw archives and config are never copied into the public tree.

## Public artifact check

The checker accepts only the documented summary, state/detail and replay-index
JSON shapes. Waiting states may contain only their identity, timestamp and status.
It rejects unknown fields, malformed/nonfinite/duplicate-key JSON, copied config
paths or YAML files, and symlinks in the public tree. It is an artifact check;
it does not replace feed, model or hosting verification.

The private file defaults to `config/priors.yaml` if present. Specify another
private file explicitly when checking poller output:

```sh
python scripts/check_public_json.py out/ --priors /private/config/priors.yaml
python scripts/check_public_json.py out/ --require-priors
```

Empty priors mappings are rejected. This standalone checker validates the file's
shape and configured scalar values; M0 remains responsible for validating full
race-registry coverage before live use.

The file follows M0's `priors: {race_id: null | {margin, margin_sd, turnout_ratio,
turnout_sd}}` schema. The checker compares public scalar values with configured
private numbers, their 3/4-decimal forms used by the publisher, and corresponding
strings. Dictionary keys are recursively checked for private identifiers and matching
private scalar tokens, including inside dynamic candidate maps. Keys are also
constrained by the public schema. Errors never
print private values or YAML contents.

Value matching is deliberately conservative: common numbers and coincidental
matches also fail. Investigate a match rather than assume it proves a leak or
suppress it automatically. A posterior still depends on its prior; this scan
cannot prove mathematical non-recoverability or detect every transformed/encoded
secret. The existing live release gate is a separate safeguard.

Without a private file, replay checks report **private-value coverage unavailable**
and validate structure only. Live output, explicit `--priors` failures, and
`--require-priors` cannot pass without a readable valid private file. Thus a replay
check alone does not complete M3's broader live privacy milestone.

Verify with `pytest -q tests/unit/test_ga_e2e.py tests/unit/test_public_json.py`.
