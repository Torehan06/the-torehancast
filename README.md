# The TörehanCast

Live election-night model and dashboard for the 2026 United States Senate races (Tuesday, November 3, 2026).

As county and district results arrive from official state election feeds, the model estimates statewide swing and turnout relative to a comparable historical baseline, accounts for within-county vote-type composition (early in-person, mail, Election Day, provisional), extrapolates to partially reported and unreported units, and runs Monte Carlo simulations to estimate each candidate's win probability and two-party margin intervals.

Non-modeled Senate races on the national map show reported votes, vote percentages, and percent reporting only (`modeled: false`), with **no forecast** and no win probability.

---

## Method

### 1. Geographic units and vote-type cells

Every state adapter normalizes raw official feeds into a common `Snapshot` of `(unit_id, vote_type)` cells:

- **Units:** Counties in 11 states, towns in Maine, and the 40 State House districts (`620L8` plan) in Alaska.
- **Vote types:** `early`, `mail`, `election_day`, `provisional`, or `all` where a state does not report a vote-type breakdown.
  - States with explicit vote-type breakdowns in their feeds (Georgia Enhanced Voting JSON, North Carolina SBE precinct TSV, South Carolina Clarity `detail.xml`, Iowa Clarity `detail.xml`) populate per-mode cells directly.
  - Florida reports county totals alongside precinct counts; because Florida law requires counties to post pre-Election-Day (early and mail) totals before precincts report, `BatchTracker` infers the `early` vs. `election_day` split from successive snapshots.
  - Minnesota publishes county totals without a mode split; its `all` cells are down-weighted until most of a county's expected vote is in.

### 2. Within-county vote-type composition

When early and mail ballots arrive before Election Day precincts finish, a partly counted county's raw margin is a biased sample of its final margin. Moreover, historical mode splits can shift sharply between cycles (for example, COVID-era mail voting in 2020 returning to in-person early voting in 2022 and 2024).

Rather than trusting the baseline's raw mode split, `Composition` (`src/torehancast/model/composition.py`) learns statewide intercept and log-size slope shifts for each vote type's share and margin gap from counties that have reported across modes tonight:

$$\text{share}_{c,v} \propto \text{baseline\_share}_{c,v} \cdot \exp(\alpha_v + \alpha'_v z_c), \qquad \text{gap}_{c,v} = \text{baseline\_gap}_{c,v} + g_v + g'_v z_c$$

where $z_c$ is the county's standardized log baseline size. Because county composition quirks are correlated across large metros, effective sample size in the composition fit is capped (`MAX_EFFECTIVE_COUNTIES = 15`).

### 3. Joint county-level swing and turnout regressions

For every county with votes in, the composition model provides an implied final turnout $\hat{T}_c$, an implied final two-party margin $\hat{m}_c$, and each partly counted county's loading matrix $L_c$ on the uncertain composition parameters.

`CountyEffectRegression` (`src/torehancast/model/regression.py`) fits a conjugate Gaussian linear model with county random effects ($\tau_{\text{county}}$, scaled inversely with the fourth root of county size) and measurement variance:

- **Prior on the intercept:** The pre-election race prior (stored only in private config and never exposed in public JSON).
- **Covariates:** Baseline partisanship, log county size, and standardized Census ACS 5-year county demographics (`white_nh`, `black_nh`, `asian_nh`, `hispanic`, `median_income`, `bachelors_plus`, `median_age`) under a tight zero-centered prior (`COVARIATE_PRIOR_SD = 0.01`). These ACS covariates capture **county-level associations** ("counties with demographic profile $X$ swung more toward party $Y$") — each is a county-level association only and says nothing about individual-voter behaviour (avoiding ecological fallacy).
- **Shared composition uncertainty:** Partly counted counties' loadings $L$ on the composition shift parameters enter the design matrix jointly, so uncertainty about how Election Day will differ from early/mail is shared across all partial counties rather than treated as independent county noise.

### 4. Historical $\tau$ and conformal-style systematic error

Historical county scatter ($\tau_{\text{swing}}$, $\tau_{\text{turnout}}$) and shared out-of-sample systematic error are estimated in `src/torehancast/model/tau.py` from the *preceding* analogous election pair (never the pair being replayed). Importantly, $\tau$ is measured **without covariate credit** (intercept only), because covariate coefficients start at zero under a tight prior early on election night; measuring $\tau$ after fitting covariates on a complete historical election would make early uncertainty bands artificially narrow.

Systematic error is estimated via repeated random half-county holdout splits, inspired in spirit by the conformal and holdout calibration ideas in the Washington Post's `elex-live-model`.

### 5. Ranked-choice voting (Maine and Alaska)

Maine and Alaska use ranked-choice voting (RCV). When candidate-level first-choice and terminal-round draws are available (`src/torehancast/model/rcv.py`), the publisher reports:

- $P(\text{outright win})$: win $>50\%$ in round 1
- $P(\text{win via RCV})$: trail or sit below $50\%$ in round 1, win after transfers
- $P(\text{winner}) = P(\text{outright win}) + P(\text{win via RCV})$
- $P(\text{no RCV needed})$: any candidate clears $50\%$ on first choices

Before RCV transfer evidence is available, RCV probability fields remain `null` rather than forcing an uncalibrated point estimate.

### 6. Privacy and release gates

- A modeled race with zero reported votes publishes only `status: "waiting"` (`modeled: true`), holding back all probability and margin fields until real votes arrive and pass the data-weight release gate.
- Non-modeled Senate races use `ResultsOnlyUpdate` (`modeled: false`), publishing only observed candidate vote counts, vote shares, and official percent reporting — with **no forecast** and no probability fields.
- `scripts/check_public_json.py` verifies that published JSON trees contain no private prior identifiers or copied scalar values from the private priors configuration.

---

## Known weaknesses

1. **Unprecedented mode shifts before any county finishes:** If a state changes election administration between the baseline and election night and no county has yet reported Election Day precincts alongside early/mail ballots, the composition model must rely on its prior width (`MIN_GAP_SHIFT_SD = 0.08`) until the first counties report both modes.
2. **Batch inference hazards in county-total feeds:** In Florida (`BatchTracker`), if a large county posts an additional batch of mail ballots *after* its first Election Day precinct has already reported, the delta tracker books that late mail increment as Election Day votes. The replay suite explicitly models this `late_mail` hazard to verify coverage holds under it.
3. **Unsplit (`all`-cell) feeds:** In states like Minnesota that report county totals without vote-type breakdowns, early reports from a county mix mail and Election Day precincts in unknown proportions. The model inflates partial-county measurement noise (`ALL_PARTIAL_SD · (1 − P) / P²`) and $\tau$ (`ALL_CELL_TAU_INFLATION = 1.25`), trading slower early convergence for protection against early-batch partisan lean.
4. **Bot protection on official state sites:** Several state election portals (Texas, Ohio, Kansas, Michigan, Maine) sit behind Cloudflare challenges or geo/IP blocks. By project policy, the poller identifies itself transparently (`torehancast/0.1`) and never spoofs browser headers or bypasses bot protection; states whose official feeds do not grant automated access by October 30 are dropped rather than scraped fragilely.

---

## What broke

Issues caught by the replay harness and synthetic regression suite during development, and how they were fixed:

1. **Per-vote-type swing against a COVID-era baseline split (`GA 2020 → 2022`):** Computing swing separately per vote type against 2020's pandemic mail/early split produced a confidently wrong `R+7.9` early projection in a `D+1.0` race because 2020 mail voters returned to in-person early voting in 2022. Fixed by modeling swing at the county total level and learning within-county vote-type composition shifts live (`Composition`).
2. **Shared composition errors treated as independent across partial counties:** Applying composition uncertainty independently to each partly counted county caused the law of large numbers to cancel out statewide mode-gap error across 100+ partial counties. Fixed by folding partial counties' composition loadings $L$ directly into the joint `CountyEffectRegression` prior covariance.
3. **Tiny provisional slivers blocking composition learning:** Requiring every vote type in a county to be reported before `Composition.fit()` used the county meant a 0.1% uncounted provisional cell blocked learning from 99.9%-complete counties. Fixed by ignoring vote types below `MAJOR_SHARE = 0.02` when checking whether a county is usable for composition learning, and weighting partial cells smoothly.
4. **Florida `BatchTracker` booking the first Election Day chunk as early vote:** When a county was first observed with `precincts_reporting > 0`, early vs. Election Day was unknowable. Fixed by freezing pre-Election-Day batches strictly while `unit_reporting == 0`, warning if a county is first seen with precincts already reporting, and enforcing Florida's legal reporting order in the replay generator.
5. **$\tau$ measured with covariate credit:** Measuring historical county scatter $\tau$ after fitting ACS covariates on a completed historical pair assumed demographic slopes the live model cannot yet estimate when only a few counties have reported (`FL` 80% coverage fell to `0.40` on R-first nights). Fixed by estimating $\tau$ and systematic error around the statewide intercept alone.
6. **Zero-vote completed counties treated as unreported:** Explicit completion of a county with zero votes (`cell_complete = 1.0`) was ignored because completion checked `V > 0`, leaving ~7,200 phantom projected votes in synthetic tests. Fixed by honoring explicit completion flags from the feed.
7. **Terminal RCV vote conservation:** Early RCV validation allowed a continuing candidate's terminal-round total to fall below their first-choice total in malformed draws. Fixed by enforcing candidate-level monotonicity between round-1 and terminal draws in `src/torehancast/model/rcv.py`.
8. **Unsplit historical baselines in `tau._composition_prior`:** In South Carolina, the 2016 statewide Clarity XML reports all county votes under a single `<VoteType>` tag while 2020 and 2024 split votes across four modes; in Minnesota, both 2016 and 2020 are unsplit `all` cells. Returning an all-zero `CompositionPrior(0, 0, 0, 0)` whenever `len(set(base.vote_type) & set(target.vote_type)) < 2` produced a singular prior covariance matrix (`LinAlgError: Singular matrix`). Fixed by estimating county composition noise and major-mode spread from `target` when `target` is split, and returning non-zero floor SDs when both elections are unsplit.

---

## Data sources and credits

- **Official state election results:**
  - **Georgia:** Georgia Secretary of State Enhanced Voting JSON API (`results.sos.ga.gov`)
  - **North Carolina:** North Carolina State Board of Elections precinct TSV archives (`dl.ncsbe.gov/ENRS`)
  - **Florida:** Florida Department of State Division of Elections results extracts (`results.elections.myflorida.com`)
  - **Iowa:** Iowa Secretary of State Clarity ENR (`electionresults.iowa.gov/IA`) and archived precinct tables (`sos.iowa.gov`)
  - **South Carolina:** South Carolina State Election Commission Clarity ENR (`enr-scvotes.org/SC`)
  - **Minnesota:** Minnesota Secretary of State election results files (`electionresultsfiles.sos.mn.gov`)
- **Demographics:** U.S. **Census** Bureau, American Community Survey (ACS) 2023 5-Year Summary File (`www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/`, tables `B01002`, `B03002`, `B15003`, `B19013`) and 2020 Census ANSI county lookup (`national_county2020.txt`).
- **Credits:** Methodological ideas for holdout systematic-error calibration and live county-level reporting models are credited to the Washington Post's [`elex-live-model`](https://github.com/washingtonpost/elex-live-model), along with open-source Clarity election-parsing work in `clarify` and `elex-clarity`.

## License

Code in this repository is licensed under the **MIT** License (see [`LICENSE`](LICENSE)). Official election results and U.S. Census ACS tables are public records in the public domain.
