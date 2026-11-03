# Feed Coverage Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans, then a fresh whole-branch review.

**Goal:** Distinguish missing feeds from races awaiting counts throughout the site.

**Architecture:** A Vite build-only reader exposes coverage IDs. Shared labels/cards use canonical IDs; untracked map fills/legend distinguish coverage visually. Existing null-RCV payload gets accurate copy.

**Tech Stack:** React, TypeScript, Vite, YAML, Vitest, Playwright, Firebase Hosting.

**Spec:** docs/superpowers/specs/2026-11-03-feed-coverage-design.md

## Global Constraints

Frontend/copy only; frozen backend and acceptance tests unchanged. Exact copy: `Not tracked` versus `no votes reported for this race`. AK stays tracked with counts and withheld null probabilities. PLAN handoff is the only private-path write. Green CI before approved merge/deploy; preserve rollback. Stop at 2026-11-04 01:00 Europe/Istanbul if not deployed.

## Review Focus

- GA/AK absent from JSON stay tracked.
- Dropped forecasts can retain results-only sources (FL/OH House).
- Malformed tracked entries stay data-unavailable.
- Valid live results/replays keep counts and probability gates.
- Only IDs enter assets, never raw config or private inputs.

### Task 1: Coverage display

- [x] Write failing inventory/UI regression tests; observe failures.
- [x] Implement web/scripts/coverage.ts, Vite virtual module, src/coverage.d.ts; export tracked/RCV IDs only.
- [x] Add data/coverage.ts isNotTracked(raceId, race) and canonical Senate-ID helper in states.ts.
- [x] Pass IDs through shared labels/cards, maps/lists/tiles; add untracked styles/legend and null-RCV copy.
- [x] Update existing frontend expectations; preserve backend acceptance tests and forecast gates.
- [x] Run focused tests, lint/typecheck/full Vitest/Playwright, both themes at 1280px/390px.

### Task 2: Release

- [x] Independent review; no actionable findings.
- [ ] Commit/push/open PR; wait for CI green on exact head.
- [ ] Capture previous Hosting release/version and rollback procedure.
- [ ] Merge approved exact head; rebuild merged tree with live VITE_DATA_BASE.
- [ ] Deploy explicitly to torehancast-2026 before cutoff; verify live widths/themes and console/CSP.
- [ ] Append factual PLAN handoff with PR, SHAs, checks, release and rollback IDs.

### Task 3: Production CSP follow-up

The live check found Zod's caught eval probe emits a CSP violation. The prior Hosting release was restored before further work. This is a frontend parser optimization setting; public schemas, acceptance thresholds, backend and CSP policy remain unchanged.

- [x] Reproduce with a browser regression applying the actual Firebase CSP to the production build.
- [x] Set Zod jitless mode before constructing public schemas; lint/typecheck/265 Vitest/39 Playwright passed. Independent review found no actionable issues.
- [ ] Independently review the follow-up, open PR and require green CI before the approved merge/redeploy.
- [ ] Repeat the actual live 1280px/390px light/dark checks, including securitypolicyviolation events.
