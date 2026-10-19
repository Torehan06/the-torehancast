# web — the TörehanCast dashboard

React + TypeScript on Vite. A US map of every 2026 Senate race, a race panel,
and loud warnings when the data is stale or unreachable. The page only **reads**
the publisher's JSON: it never computes a probability, projection or swing.

```sh
npm ci
npm run dev        # http://localhost:5173, serves fixtures/demo/ as data
npm test           # Vitest (unit + fixture cases) then Playwright (headless Chrome)
npm run build      # → dist/
```

`FIXTURE=cases/waiting npm run dev` previews another fixture set
(see [fixtures/README.md](fixtures/README.md)).

## Configuration (build time)

| Variable | Default | Meaning |
|---|---|---|
| `VITE_DATA_BASE` | `data/replay/` | Folder holding `summary.json`. Production: `https://storage.googleapis.com/<bucket>/data/live/` |
| `VITE_POLL_MS` | `20000` | Poll interval (matches the bucket's `max-age=20`) |
| `VITE_STALE_AFTER_S` | `120` | Snapshot age that triggers the stale banner |

There is deliberately no runtime override (no `?data=` parameter), so nobody can
link to this page with someone else's numbers behind it.

## Layout

| Path | What |
|---|---|
| `src/data/contract.ts` | The JSON contract as zod schemas; TypeScript types are inferred from them |
| `src/data/parse.ts` | Per-race tolerant parsing for the page; strict validation for tests |
| `src/data/display.ts` | Display rules: when probabilities show, who leads, number formats |
| `src/data/freshness.ts` | Fresh / stale / failing logic (F4) |
| `src/data/states.ts` | The 50 states and the 35 with a 2026 Senate race |
| `src/hooks/useSummaryPoll.ts` | Polling, never going backwards in time |
| `src/components/` | Map, race list, race panel, banners, legend |
| `e2e/` | Playwright specs (map, keyboard, phone width, network, stale, failure) |
| `scripts/validate-json.ts` | Validates a directory of published JSON; used by `tests/web/` in Python |

## Design

"Ballot stock": the look comes from the official ballot, not the newsroom.
Cool tinted card-stock paper, blue-black ink, and the filled ballot oval as the
one recurring mark (wordmark, map key, list markers, probability bars). States
with a race but no votes are hatched like an unmarked ballot. Type is Public Sans,
the US government's USWDS typeface (OFL), bundled through `@fontsource-variable`.
The one animation: a state's colour eases over when a new snapshot changes who
leads (off under `prefers-reduced-motion`).

Dark is the default; the oval switch in the masthead changes to light and the
choice is saved in `localStorage` (index.html applies it before first paint).
Below the map, the 13 registry seats (`SWING_SEATS` in `src/data/states.ts`) get
tiles led by the favourite's win probability in big party-coloured type. The list
only decides placement: a tile shows a number only when its JSON has
`modeled: true` with votes in, and never shows a vote share in that slot. Stale data is marked in highlighter
yellow; a failing fetch inverts to ink, so neither can be mistaken for a party colour.

## Rules the code enforces

- Probabilities appear only when a race's JSON says `modeled: true` **and** votes
  are in. A zero-vote probability is pure prior, so the page refuses to show one
  even if the publisher sends it.
- Results-only races (`modeled: false`) show counts, shares and % reporting, and no
  probability element at all.
- A race with no votes, or missing from the JSON, shows exactly
  "no votes reported for this race".
- Maine and Alaska show P(outright), P(via RCV), P(overall) and P(no RCV needed);
  a `null` shows as "—" (not yet estimated), never as a number.
- Colour shows only who leads; the number is always printed next to it.
  Okabe–Ito blue/vermilion, readable with common colour-vision deficiencies.
- No analytics, trackers or third-party fonts. The map is us-atlas (US Census
  boundaries, bundled), so the page talks only to its own origin and the data bucket.

## Deploy (Firebase Hosting)

`firebase.json` and `.firebaserc` are at the repo root. **Always pass
`--project torehancast-2026`**: a `firebase use` set in a parent folder overrides
`.firebaserc`, and a deploy without the flag can land in a different project.

```sh
cd web && npm run build:staging && cd ..   # build plus fixtures/demo at /data/replay/
firebase hosting:channel:deploy staging --expires 30d --project torehancast-2026
```

`build:staging` is the only build that puts data in `dist/`. A production build
reads live JSON from the GCS bucket via `VITE_DATA_BASE` and ships no data.

Headers (in `firebase.json`): `no-cache` by default, so a new release reaches
everyone on the next load; `max-age=31536000, immutable` on hashed `/assets/**`;
`max-age=20` on staging `/data/**`. The CSP allows scripts only from the site's
own origin (which is why the theme script is `public/theme-init.js`, not inline)
and network requests only to the site and `storage.googleapis.com`.

## Browser tests

Playwright uses the installed Google Chrome by default. In CI, run
`npx playwright install chromium` and set `PLAYWRIGHT_CHANNEL=chromium`.

## Contract drift

`pytest -q tests/web/test_schema_matches_types.py` (repo root) runs the real
publisher and validates its output with these schemas. It also holds a strict
`xfail` for the M3 fields (`modeled`, `votes`, `vote_share`, `pct_reporting`) the
publisher doesn't emit yet: once M3 lands it starts passing, fails as XPASS, and
the marker must be removed.
