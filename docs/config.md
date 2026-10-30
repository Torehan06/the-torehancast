# Poller configuration

Run from the repository root with the project environment active:

```sh
python -m torehancast.config validate
git check-ignore config/priors.yaml
```

The validator checks structure, field types, numeric bounds, duplicate YAML
keys, and race IDs across files. It makes no network requests and writes no
files. It accepts pending feeds and unset priors, and reports their counts.
Success means the files are valid drafts; it does not certify live readiness.
Use `--config-dir /path/to/config` to validate another complete directory.
Invalid files return exit code 1 without printing prior values or YAML source.

## Files

- `races.yaml`: the modeled races in PLAN.md (13 Senate races and 63 House
  districts), baseline exceptions, RCV flags, geographic units and
  implementation status. The `done` status tracks
  adapter/replay work; it does not mean the live pipeline is ready.
- `feeds.yaml`: one entry per race. Each contains an adapter name, complete
  feed URL, election ID, status, and optional string-valued request `params`.
  `reference_url` is for discovery, and may point to an archived election.
  A feed marked `ready` requires a non-null adapter, URL and election ID.
  The URLs must use HTTPS without embedded credentials. Null fields explicitly
  represent settings that remain unverified. Do not use a historical reference
  URL as the live feed.
- `priors.example.yaml`: the shared template. Every prior is initially null.
- `priors.yaml`: the optional private file, ignored by Git. Copy the template
  locally and fill in values by hand. Each prior is null or a mapping with
  `margin`, `margin_sd`, `turnout_ratio`, and `turnout_sd`, using the same units
  as `RacePrior`. Margin is the two-party D minus R fraction, between -1 and 1.
  Standard deviations and the turnout ratio must be finite and positive.

Keep every race ID in both the feeds and priors files, including blocked races;
use null for an unset prior. Unknown fields fail validation to catch typos.
The example is checked but never supplies runtime priors. Without a private
file, every runtime prior is unset. The private file must list every race;
missing entries do not silently inherit an example prior. Invalid private
config, including a broken file symlink, fails validation.

House race IDs are `2026-XX-HNN`, or `2026-XX-HAL` for an at-large seat. A
`house` race must name a real district under the 2020-census apportionment in
`src/torehancast/districts.py`, and only `house` races may use that ID form.

## Results-only races

Every 2026 federal race that isn't modeled (22 Senate races and the other 372 House
districts) shows vote totals only. Each state has `config/results/<ST>.yaml`, and
a race may be modeled, results-only, or explicitly `none`, never two of these. The
coverage test in `tests/unit/test_config.py` fails if any of the 35 Senate or 435
House race IDs is in none of the three.

```yaml
results:
  sources:
    sbe:                          # one download, many contests
      same_as: 2026-NC-SEN        # borrow the modeled feed's adapter, url, election_id, polls_close
      status: pending             # pending | ready | blocked | dropped
      contests:
      - office: house             # house | senate
        districts: all            # every district that isn't modeled, or a list: [2, 3]
        template: US HOUSE OF REPRESENTATIVES DISTRICT {n:02d}
        sides: {Jane Doe: D2}     # optional: ballot name -> side key
  none:
    senate: 'W4: no verified official feed yet.'
    house: 'W4: no verified official feed yet.'   # every district not covered above
```

- A source either sets `same_as` (a modeled race in the same state) or its own
  `adapter`, `url`, `election_id`, `params`, `reference_url` and `polls_close`.
- `template` is the contest as the feed names it, with `{n}` for the district
  number (Python format spec, so `{n:02d}` zero-pads). Null until it's checked
  against the 2024 archive and the 2026 file.
- A `ready` source needs an adapter, a URL, `polls_close` and a template for every
  contest. It doesn't need a D/R mapping: uncontested and same-party top-two
  races are fine.
- Side keys are automatic (`results_only.totals`): the feed's party label gives
  the letter (DEM/DFL → D, REP → R, LIB/LPF → L, GRE/GRN → G, CON/CST → C,
  IND/NPA/UNA → I), D and R come first, and a second candidate of one party gets
  D2. Keys follow feed order, never vote order, so they don't change during the
  night. Write-ins, unknown or ambiguous labels (SC's `UNC` is the United Citizens
  Party; its write-in line is `NON`) and anyone past five named candidates pool
  into `other`. `sides` overrides this for a named ballot line.
- Florida's template is the extract's race code plus district, `USR:{n:03d}`.
- Check a state's templates against its live file with
  `python -m torehancast.feedcheck --contests ST` (from the VM): it prints
  expected vs found districts and each contest's candidates and votes.
- `none` keys are `senate`, `house` or a single House race ID. An explicit ID
  takes its own reason over the `house` catch-all.

`load_results(config, directory)` reads these files separately from
`load_config`, so a broken results file never stops the modeled races from loading.

Historical House elections for a state go in `config/house/<ST>.yaml` under an
`elections:` key, in the same shape as a state's block in `elections.yaml`.
`elections.load()` reads both, and a key may be defined in only one of them.

Adding a modeled race means adding its ID to the private `priors.yaml` too
(null until set), on the poller and in the private bucket, **before** deploying
the code that registers it. Otherwise the poller can't load its config at
startup.

## Loading and privacy

```python
from pathlib import Path
from torehancast.config import load_config

settings = load_config(Path("config"))
feed = settings.feeds["2026-GA-SEN"]
prior = settings.priors["2026-GA-SEN"]  # None until privately configured
```

`load_config` reads fresh files on every call. The future poller must call it
each cycle and pass the feed settings to the adapter; this milestone adds
the schema and loader, not a running live poller. Existing historical replay
settings in `elections.yaml` and `replay.yaml` remain independent.

The real priors file belongs on the poller and, once approved and provisioned,
in the separate private config bucket. Never upload any config file to the
public site bucket or include it in dashboard JSON. This work provisions no
cloud resources. Live feed verification, private-bucket copying, and the
publisher's public-JSON audit remain later PLAN.md work.
