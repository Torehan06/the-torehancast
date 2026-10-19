"""From a results snapshot to win probabilities.

For one race:
  1. Line up every county's baseline (by vote type) with what has reported.
  2. Learn tonight's vote-type composition from counties that have finished.
  3. For partly counted counties, use that composition to infer their final
     turnout and margin ("early and mail are in; Election Day will be ~35% of the
     county and lean 20 points more R").
  4. Fit county-level turnout and swing regressions on complete + partial counties.
  5. Draw many outcomes for everything still out and add them to what's in.

Margins are two-party: (D − R) / (D + R), as fractions (0.025 = D+2.5).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..schema import ALL, EARLY, ELECTION_DAY, PROVISIONAL, Snapshot
from .composition import Composition, CompositionPrior, baseline as baseline_composition
from .regression import CountyEffectRegression, Priors, size_scale
from .swing import ALL_CELL_TAU_INFLATION, PRECINCT_SD, covariates, design, measurement_sd, turnout_design
from .tau import HistoricalParams, wide

@dataclass(frozen=True)
class RacePrior:
    margin: float  # expected two-party D−R margin (+0.025 = D+2.5)
    margin_sd: float
    turnout_ratio: float  # expected two-party votes relative to the baseline
    turnout_sd: float  # relative sd of that ratio


@dataclass
class Result:
    p_win: dict[str, float]
    margin_median: float
    margin_80: tuple[float, float]
    margin_95: tuple[float, float]
    reported_votes: int
    expected_votes: float
    share_counted: float
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "p_win": self.p_win,
            "margin": {"median": self.margin_median, "p80": self.margin_80, "p95": self.margin_95},
            "reported_votes": self.reported_votes,
            "expected_votes": round(self.expected_votes),
            "share_counted": self.share_counted,
            "warnings": self.warnings,
        }


def _stack_cov(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Block-diagonal [[a, 0], [0, b]]."""
    out = np.zeros((a.shape[0] + b.shape[0],) * 2)
    out[: a.shape[0], : a.shape[0]] = a
    out[a.shape[0] :, a.shape[0] :] = b
    return out


class RaceModel:
    def __init__(
        self,
        baseline: pd.DataFrame,
        prior: RacePrior,
        params: HistoricalParams,
        batch_vote_types: tuple[str, ...] = (),
        demographics: pd.DataFrame | None = None,
        synthetic_split: dict | None = None,
    ):
        """`batch_vote_types`: vote types a county reports in one go (e.g. GA early/mail).

        `synthetic_split`: for states whose baseline has no vote types but whose feed
        lets us infer them (Florida), the assumed pre-Election-Day share and gap, plus a
        composition prior — {early_share, gap, shift_sd, share_sd, gap_shift_sd, gap_sd}.
        """
        self.synthetic_split = synthetic_split
        self.baseline = baseline
        self.prior = prior
        self.params = params
        self.batch_vote_types = batch_vote_types
        self.demographics = demographics

    # -- 1. line up baseline and reported ------------------------------------------
    def _split_baseline(self) -> pd.DataFrame:
        """County totals → early / election_day rows using the configured split."""
        s, g = self.synthetic_split["early_share"], self.synthetic_split["gap"]
        b = self.baseline.groupby("unit_id", as_index=False)[["D", "R"]].sum()
        n, m = b.D + b.R, (b.D - b.R) / (b.D + b.R).where(b.D + b.R > 0, 1)
        rows = []
        for vt, share, margin in ((EARLY, s, m + g * (1 - s)), (ELECTION_DAY, 1 - s, m - g * s)):
            votes, diff = n * share, n * share * margin
            rows.append(pd.DataFrame({"unit_id": b.unit_id, "vote_type": vt, "D": (votes + diff) / 2, "R": (votes - diff) / 2}))
        return pd.concat(rows, ignore_index=True)

    def _arrays(self, snap: Snapshot):
        base = self.baseline
        if self.synthetic_split:
            base, split = self._split_baseline(), True
        else:
            split = not ({c.vote_type for c in snap.cells} <= {ALL}) or not snap.cells and set(base.vote_type) != {ALL}
        if not split:
            base = base.groupby("unit_id", as_index=False)[["D", "R"]].sum().assign(vote_type=ALL)
        units = sorted(base.unit_id.unique())
        types = sorted(base.vote_type.unique())
        bn, bd = wide(base, units, types)

        rn = np.zeros_like(bn)
        rd = np.zeros_like(bd)
        u_index = {u: i for i, u in enumerate(units)}
        t_index = {t: j for j, t in enumerate(types)}
        extra = np.zeros(2)  # (two-party votes, D−R) for cells we can't place
        warnings = list(snap.warnings)
        for c in snap.cells:
            D, R = c.votes.get("D", 0), c.votes.get("R", 0)
            i, j = u_index.get(c.unit_id), t_index.get(c.vote_type)
            if i is None or j is None:
                if D + R:
                    warnings.append(f"reported cell not in baseline: {c.unit_id}/{c.vote_type}")
                extra += (D + R, D - R)
                continue
            rn[i, j] += D + R
            rd[i, j] += D - R
        return units, types, split, bn, bd, rn, rd, extra, warnings

    # -- how complete is each cell? -----------------------------------------------
    def _completion(self, units, types, bn, rn, snap: Snapshot) -> tuple[np.ndarray, np.ndarray]:
        """(completion, measured): measured is completion where the feed told us, else 0."""
        prior_expected = bn * self.prior.turnout_ratio
        e = np.zeros_like(bn)
        measured = np.zeros_like(bn)
        for i, u in enumerate(units):
            for j, vt in enumerate(types):
                known = snap.cell_complete.get((u, vt))
                if known == 1.0:  # includes "fully reported, zero votes"
                    e[i, j] = measured[i, j] = 1.0
                elif rn[i, j] == 0:
                    continue
                elif vt in (ELECTION_DAY, PROVISIONAL, ALL) and u in snap.unit_reporting:
                    e[i, j] = measured[i, j] = snap.unit_reporting[u]
                elif vt in self.batch_vote_types and known is None and not snap.cell_complete:
                    e[i, j] = measured[i, j] = 1.0  # feed gives no status; arrives in one go
                else:  # partly reported, extent unknown: compare with what we expected
                    e[i, j] = min(rn[i, j] / max(prior_expected[i, j], 1.0), 0.95)
        return e, measured

    # -- 2-5 ---------------------------------------------------------------------
    def run(self, snap: Snapshot, n_draws: int = 10_000, seed: int = 0) -> Result:
        rng = np.random.default_rng(seed)
        p = self.params
        units, types, split, bn, bd, rn, rd, extra, warnings = self._arrays(snap)
        e, measured = self._completion(units, types, bn, rn, snap)

        B = bn.sum(axis=1)  # baseline county two-party votes
        M = bd.sum(axis=1) / np.maximum(B, 1)  # baseline county margin
        V = rn.sum(axis=1)  # reported votes
        Dr = rd.sum(axis=1)  # reported D−R
        has_type = bn > 0
        complete = (V > 0) & np.all((e >= 1.0) | ~has_type, axis=1)
        partial = (V > 0) & ~complete

        # 2. Composition, learned from complete counties.
        comp_prior = p.composition
        if self.synthetic_split:
            ss = self.synthetic_split
            comp_prior = CompositionPrior(ss["shift_sd"], ss["share_sd"], ss["gap_shift_sd"], ss["gap_sd"])
        comp = Composition(comp_prior, *baseline_composition(bn, bd), size=B)
        if split:
            comp.fit(np.where(has_type, measured, 1.0), rn, rd)
        share, gap = comp.predicted()

        # 3. Implied final turnout and margin for every county with votes in.
        counted = np.clip((share * e).sum(axis=1), 1e-3, 1.0)
        counted = np.where(complete, 1.0, counted)
        T_hat = np.where(V > 0, V / counted, 0.0)
        m_obs = np.where(V > 0, Dr / np.maximum(V, 1), 0.0)
        m_hat = m_obs - np.where(complete, 0.0, (share * e * gap).sum(axis=1) / counted)
        sd_m = np.where(complete, 1e-4, measurement_sd(counted, comp_prior.gap_sd, split))
        sd_t = np.where(complete, 1e-4, measurement_sd(counted, comp_prior.share_sd, split))
        # Plus precinct heterogeneity inside partly counted cells.
        part = (e > 0) & (e < 1)
        w_in = share * e / counted[:, None]
        precinct_var = np.where(part, (w_in * PRECINCT_SD) ** 2 * (1 - e) / np.maximum(e, 1e-3), 0.0).sum(axis=1)
        sd_m = np.sqrt(sd_m**2 + precinct_var)

        # Tonight's composition estimates are uncertain too, and that error is shared by
        # every partly counted county. It goes into the regressions as extra parameters:
        # a partial county's implied margin (turnout) loads on each vote type's gap
        # (share) shift by how much its counted part over- or under-represents that type,
        # with tonight's composition posterior as the prior. One joint Gaussian model, so
        # the shared error is accounted for exactly and uncertainty only shrinks as
        # results arrive.
        load = np.where(partial[:, None] & split, -(w_in - share), 0.0)  # (counties, types)
        L = np.concatenate([np.stack([load[:, j], load[:, j] * comp.z], axis=1) for j in range(len(types))], axis=1)

        def block_diag(covs: np.ndarray) -> np.ndarray:
            out = np.zeros((2 * len(covs), 2 * len(covs)))
            for j, c in enumerate(covs):
                out[2 * j : 2 * j + 2, 2 * j : 2 * j + 2] = c
            return out

        # 4. County-level regressions on counties with votes in.
        cov = covariates(np.array(units), M, B, self.demographics)
        X, sds = design(cov, B)
        county = np.arange(len(units))
        county_scale = size_scale(B, p.reference_votes)
        inflation = 1.0 if split else ALL_CELL_TAU_INFLATION
        obs = V > 0
        statewide_base = float(np.average(M, weights=B))
        no_load = np.zeros_like(L)  # predictions are of true values, free of measurement error

        sds[0] = self.prior.margin_sd
        swing = CountyEffectRegression(
            Priors(
                mean=np.r_[self.prior.margin - statewide_base, np.zeros(X.shape[1] - 1 + L.shape[1])],
                cov=_stack_cov(np.diag(sds**2), block_diag(comp.g_cov)),
                tau_county=p.tau_swing * inflation,
                tau_cell=1.0,
            ),
            county_scale,
        )
        Xs = np.hstack([X, L])
        swing.fit(Xs[obs], (m_hat - M)[obs], county[obs], np.ones(obs.sum()), sd_m[obs])
        # How much the data has said about the statewide swing, relative to the prior
        # (used by the publisher's optional "data weight" release gate).
        prior_precision = 1.0 / self.prior.margin_sd**2
        self.last_data_weight = (1.0 / swing.theta_cov[0, 0] - prior_precision) / prior_precision
        swing_draw = swing.draw(rng, n_draws, np.hstack([X, no_load]), county, sd_m, add_cell_noise=False)

        Xt, t_sds = turnout_design(cov, B)
        t_sds[0] = np.sqrt(np.log1p(self.prior.turnout_sd**2))
        turnout = CountyEffectRegression(
            Priors(
                mean=np.r_[np.log(self.prior.turnout_ratio), np.zeros(Xt.shape[1] - 1 + L.shape[1])],
                cov=_stack_cov(np.diag(t_sds**2), block_diag(comp.alpha_cov)),
                tau_county=p.tau_turnout,
                tau_cell=1.0,
            ),
            county_scale,
        )
        Xtt = np.hstack([Xt, L])
        y_t = np.log(np.maximum(T_hat, 1) / np.maximum(B, 1))
        turnout.fit(Xtt[obs], y_t[obs], county[obs], np.ones(obs.sum()), sd_t[obs])
        turnout_draw = turnout.draw(rng, n_draws, np.hstack([Xt, no_load]), county, sd_t, add_cell_noise=False)

        # The historical systematic error applies only to votes still out (step 5).
        shared_swing = p.systematic_swing * inflation * rng.standard_normal((n_draws, 1))
        shared_turnout = p.systematic_turnout * rng.standard_normal((n_draws, 1))

        # 5. Final county outcomes.
        # Unreported counties: straight from the regressions; nothing is in yet.
        T = B * np.exp(turnout_draw + shared_turnout)
        diff = T * np.clip(M + swing_draw + shared_swing, -1, 1)

        # Partly counted counties: work on what's *left*, on scales that can't leave the
        # possible range, so the median of each draw stays where the projection is:
        #   share counted  → logit scale (remaining votes can never go negative)
        #   remaining margin → atanh scale (it can never leave ±100%)
        # Clipping or flooring instead would skew the outcome toward whichever way the
        # outstanding vote types lean.
        if partial.any():
            # Centre: the regressions' posterior median (which already blends the county's
            # own count with what similar counties did), never below what's counted.
            Tc = np.maximum(B * np.exp(np.median(turnout_draw, axis=0)), V * 1.001)
            counted = np.where(partial, V / Tc, counted)
            remaining_c = Tc - V
            d_log_t = turnout_draw - np.median(turnout_draw, axis=0) + shared_turnout
            counted_draw = 1.0 / (1.0 + (1.0 - counted) / counted * np.exp(d_log_t))
            T_part = V / counted_draw
            m_center = np.median(M + swing_draw, axis=0)
            m_rest_c = np.clip((Tc * m_center - Dr) / np.maximum(remaining_c, 1.0), -0.99, 0.99)
            d_m_rest = (M + swing_draw - m_center) * Tc / np.maximum(remaining_c, 1.0) + shared_swing
            m_rest = np.tanh(np.arctanh(m_rest_c) + d_m_rest / (1.0 - m_rest_c**2))
            diff_part = Dr + (T_part - V) * m_rest
            T = np.where(partial, T_part, T)
            diff = np.where(partial, diff_part, diff)

        T = np.where(complete, V, T)
        diff = np.where(complete, Dr, diff)

        final_diff = diff.sum(axis=1) + extra[1]
        final_total = T.sum(axis=1) + extra[0]
        final_margin = final_diff / final_total

        # Central projections per county and cell: medians over draws, because turnout
        # draws are skewed and their mean overstates the likely outcome. Used by the
        # county view and by the on-expectation replay test. Finished cells keep their
        # reported values.
        T_med = np.median(T, axis=0)
        m_med = np.median(diff / np.maximum(T, 1), axis=0)
        cell_votes = share * T_med[:, None]
        cell_diff = cell_votes * (m_med[:, None] + gap)
        done = (e >= 1.0) | complete[:, None]
        self.last_projection = {
            "units": units,
            "types": types,
            "votes": np.where(done, rn, np.maximum(cell_votes, rn)),
            "diff": np.where(done, rd, cell_diff),
        }

        self.last_counties = pd.DataFrame(
            {
                "unit_id": units,
                "baseline_votes": B,
                "baseline_margin": M,
                "reported_votes": V,
                "reported_margin": m_obs,
                "status": np.where(complete, "complete", np.where(partial, "partial", "none")),
                "counted_share": np.where(V > 0, V / np.maximum(T_med, 1), 0.0),
                "expected_votes": T_med,
                "expected_margin": m_med,
            }
        )

        p_d = float(np.mean(final_diff > 0))
        q = np.quantile(final_margin, [0.025, 0.10, 0.5, 0.90, 0.975])
        reported_votes = int(V.sum() + extra[0])
        mean_expected = float(final_total.mean())
        return Result(
            p_win={"D": p_d, "R": 1.0 - p_d},
            margin_median=float(q[2]),
            margin_80=(float(q[1]), float(q[3])),
            margin_95=(float(q[0]), float(q[4])),
            reported_votes=reported_votes,
            expected_votes=mean_expected,
            share_counted=reported_votes / mean_expected if mean_expected else 0.0,
            warnings=warnings,
        )
