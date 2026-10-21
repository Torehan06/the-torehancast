# Fixtures

JSON the page is tested against. Every file here must pass the strict contract
(`src/data/contract.ts`); `src/data/fixtures.test.ts` checks that.

| Directory | What it is | Shape |
|---|---|---|
| `replay-ga/` | Verbatim output of `python -m torehancast.replay.e2e --state GA --out <dir>` (2020→2022 GA Senate, order `random`, seed 0), regenerated Oct 21 for contract v2: `summary.json`, `races/2026-GA-SEN.json`, `index.json` and 29 `frames/`. Real 2022 results, published under the live race's ID. | Contract v2. |
| `cases/waiting/` | Election night before any votes: all 13 modeled races `waiting`. | Publisher's waiting shape. |
| `cases/partial-nonmodeled/` | Results-only races (IL with % reporting, VA without), no forecast. | Contract v1 (M3/F7 fields). |
| `cases/partial-modeled/` | Georgia part-counted, `modeled: true`. | Contract v1. |
| `cases/rcv-null/` | Maine and Alaska with every RCV probability `null` (`awaiting_first_choices`). AK carries no vote counts. | Contract v1 + `docs/rcv.md`. |
| `cases/final/` | Georgia and Illinois fully counted. | Contract v1. |
| `demo/` | A mixed night for `npm run dev` and screenshots. `mode: replay`. | Contract v1. |

Detail files live at `races/{race_id}.json` and exist only for modeled races.
Everything except `replay-ga/` uses made-up candidates ("GA Fixture A (Dem)") and
made-up numbers. "Contract v1" fields are ones the publisher will emit after
PLAN.md M3 (`modeled`, `votes`, `vote_share`, `pct_reporting`).

To refresh `replay-ga/`, rerun the e2e command into an empty directory and copy
its `data/replay/` here.

`npm run dev` serves `demo/` at `/data/replay/`; pick another with
`FIXTURE=cases/waiting npm run dev`.
