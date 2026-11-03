# Election-night coverage display

Show `Not tracked` for races with no source and keep `no votes reported for this race` for configured races awaiting counts, including unavailable GA/AK files. Apply to Senate map, swing tiles, other-race rows, House tiles, browsing rows and panels. Use a solid untracked fill and legend entry distinct from waiting hatches.

Selected approach: Vite reads existing races/feeds/results config at build time and exports only tracked and ranked-choice race IDs. No raw config, URLs, notes, candidate maps, priors or private inputs enter the bundle. Coverage is 103 races (16 modeled + 87 results-only). Payload absence cannot distinguish unpublished files from no source; a frontend state list is excluded. Valid published live results remain displayable, preserving actual counts and replays.

Both AK races remain tracked. Existing publisher output already includes counts and null RCV probabilities. Explain that win probability is withheld because ranked-choice simulation is not yet available, preserving probability gates and estimated RCV replay fixtures.

Frontend/build/copy/frontend regression tests only. No frozen backend, priors, thresholds or backend acceptance changes. PLAN handoff is the only private-path write. User approved merge/deploy after checks. Require lint, typecheck, Vitest, Playwright, independent review and green CI, then verify 1280px/390px in both themes with no console/CSP errors. Preserve prior Hosting release for rollback; deploy explicitly to torehancast-2026 before 2026-11-04 01:00 Europe/Istanbul or stop.
