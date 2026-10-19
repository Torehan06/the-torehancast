"""How much counties scatter around the statewide swing, learned from history.

Given an earlier pair of elections (baseline → target), measure:

  * τ for swing and turnout: county scatter around the statewide swing
  * systematic error: how wrong the aggregate is for held-out counties, beyond chance
  * composition: how much vote-type shares and gaps shift, statewide and by county

The pair is always one step *before* the pair being modelled, so a replay never
learns its own answer: GA's 2020 → 2022 replay uses 2016 → 2020.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from . import composition
from .regression import size_scale

MIN_TAU = 0.004  # never claim counties are more predictable than ±0.4 pts
# Vote-type gaps can move a lot between cycles: mail went heavily D in 2020, and
# early in-person moved sharply R in 2024. One historical pair can miss that, so
# the prior on gap shifts never goes below this. Chosen after the GA 2022 → 2024
# replay showed ±4.7 pts (from 2014 → 2016) was far too confident.
MIN_GAP_SHIFT_SD = 0.08


@dataclass(frozen=True)
class HistoricalParams:
    tau_swing: float  # county swing scatter (sd at the reference county size)
    tau_turnout: float  # county log-turnout scatter (sd at the reference size)
    systematic_swing: float  # shared error of outstanding counties' swing
    systematic_turnout: float  # shared error of outstanding counties' log turnout
    composition: composition.CompositionPrior
    reference_votes: float  # median baseline county two-party votes

    def to_dict(self) -> dict:
        return asdict(self)


def county_table(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse a unit × vote-type frame to county two-party totals."""
    g = df.groupby("unit_id", as_index=False)[["D", "R"]].sum()
    g["n"] = g.D + g.R
    g["m"] = (g.D - g.R) / g.n.where(g.n > 0, 1)
    return g


def wide(df: pd.DataFrame, units: list[str], types: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """(counties, types) arrays of two-party votes and D−R."""
    votes = df.assign(n=df.D + df.R, d=df.D - df.R).pivot_table(
        index="unit_id", columns="vote_type", values=["n", "d"], aggfunc="sum", fill_value=0
    )
    votes = votes.reindex(index=units, fill_value=0)
    n = votes["n"].reindex(columns=types, fill_value=0).to_numpy(dtype=float)
    d = votes["d"].reindex(columns=types, fill_value=0).to_numpy(dtype=float)
    return n, d


def _shrunk(X: np.ndarray, y: np.ndarray, noise_sd: np.ndarray, prior_sd: np.ndarray) -> np.ndarray:
    """Posterior mean under the live model's prior: wide intercept, tight covariates."""
    prior_sd = np.where(np.isnan(prior_sd), 1.0, prior_sd)
    P = np.diag(1.0 / prior_sd**2) + (X / noise_sd[:, None] ** 2).T @ X
    return np.linalg.solve(P, X.T @ (y / noise_sd**2))


def _fit_tau(X, y, prior_sd, scale, iterations: int = 4) -> tuple[np.ndarray, float]:
    """Alternate: fit with the current τ, re-measure τ from the residuals."""
    tau = max(float(np.std(y - np.average(y))), MIN_TAU)
    for _ in range(iterations):
        coef = _shrunk(X, y, tau * scale, prior_sd)
        tau = max(float(np.std((y - X @ coef) / scale)), MIN_TAU)
    return coef, tau


def _systematic(X, y, w, scale, tau, prior_sd, n_splits=300, seed=0) -> float:
    """Fit on a random half of counties, predict the other half, repeat.

    The spread of the vote-weighted aggregate error, minus what independent county
    scatter alone would produce, is the shared ("systematic") error. Borrowed in
    spirit from the conformal checks in the Washington Post's elex-live-model.
    """
    rng = np.random.default_rng(seed)
    errors, independent = [], []
    for _ in range(n_splits):
        test = rng.random(len(y)) < 0.5
        if test.all() or not test.any():
            continue
        coef = _shrunk(X[~test], y[~test], tau * scale[~test], prior_sd)
        share = w[test] / w[test].sum()
        errors.append(np.sum(share * (y[test] - X[test] @ coef)))
        independent.append(np.sum((share * scale[test] * tau) ** 2))
    return float(np.sqrt(max(np.mean(np.square(errors)) - np.mean(independent), 0.0)))


def _composition_prior(base: pd.DataFrame, target: pd.DataFrame) -> composition.CompositionPrior:
    types = sorted(set(base.vote_type) & set(target.vote_type))
    units = sorted(set(base.unit_id) & set(target.unit_id))
    if len(types) < 2:
        target_types = sorted(set(target.vote_type))
        if len(target_types) < 2:
            return composition.CompositionPrior(0.10, 0.05, MIN_GAP_SHIFT_SD, 0.02)
        # Base was unsplit (e.g. 2016 statewide Clarity files before early/mail were
        # broken out), while target has vote types. Measure county composition noise
        # around target's statewide profile, and use target's major-mode spread relative
        # to an unsplit baseline for the shift prior.
        tn, td = wide(target, units, target_types)
        keep = tn.sum(axis=1) > 0
        ts, tg = composition.baseline(tn[keep], td[keep])
        w = tn[keep].sum(axis=1)
        log_ts = np.log(ts)
        log_ts -= log_ts.mean(axis=1, keepdims=True)
        alpha = np.average(log_ts, axis=0, weights=w)
        share_resid = log_ts - alpha
        g = np.average(tg, axis=0, weights=w)
        gap_resid = tg - g
        major = np.average(ts, axis=0, weights=w) >= composition.MAJOR_SHARE
        log_major = np.log(ts[:, major])
        log_major -= log_major.mean(axis=1, keepdims=True)
        alpha_major = np.average(log_major, axis=0, weights=w)
        return composition.CompositionPrior(
            shift_sd=max(float(np.sqrt(np.mean(alpha_major**2))), 0.10),
            share_sd=max(float(np.sqrt(np.average(share_resid**2, weights=ts * w[:, None]))), 0.05),
            gap_shift_sd=max(float(np.sqrt(np.mean(g[major] ** 2))), MIN_GAP_SHIFT_SD),
            gap_sd=max(float(np.sqrt(np.average(gap_resid**2, weights=ts * w[:, None]))), 0.02),
        )
    bn, bd = wide(base, units, types)
    tn, td = wide(target, units, types)
    keep = (bn.sum(axis=1) > 0) & (tn.sum(axis=1) > 0)
    bs, bg = composition.baseline(bn[keep], bd[keep])
    ts, tg = composition.baseline(tn[keep], td[keep])
    w = tn[keep].sum(axis=1)

    log_shift = np.log(ts) - np.log(bs)
    log_shift -= log_shift.mean(axis=1, keepdims=True)
    alpha = np.average(log_shift, axis=0, weights=w)
    share_resid = log_shift - alpha
    gap_shift = tg - bg
    g = np.average(gap_shift, axis=0, weights=w)
    gap_resid = gap_shift - g
    # County noise: share-weighted, so a tiny provisional slice doesn't dominate.
    return composition.CompositionPrior(
        shift_sd=max(float(np.sqrt(np.mean(alpha**2))), 0.10),
        share_sd=max(float(np.sqrt(np.average(share_resid**2, weights=ts * w[:, None]))), 0.05),
        gap_shift_sd=max(float(np.sqrt(np.mean(g**2))), MIN_GAP_SHIFT_SD),
        gap_sd=max(float(np.sqrt(np.average(gap_resid**2, weights=ts * w[:, None]))), 0.02),
    )


def estimate(base: pd.DataFrame, target: pd.DataFrame) -> HistoricalParams:
    """τ and systematic error from a historical pair, *without* covariate credit.

    Tonight's regression has covariates, but their coefficients start at zero under a
    tight prior and stay near it until many counties are in. If τ were measured after
    fitting covariates on a full historical pair, it would assume effects the live
    model can't yet see, and early bands would be too narrow (they were: FL coverage
    fell to 0.40 on R-heavy-first nights). So τ is the scatter around the statewide
    swing alone; whatever the covariates learn tonight only sharpens the centre.
    """
    b, t = county_table(base), county_table(target)
    df = b.merge(t, on="unit_id", suffixes=("_b", "_t"))
    df = df[(df.n_b > 0) & (df.n_t > 0)]
    n_b = df.n_b.to_numpy(dtype=float)
    ref = float(np.median(n_b))
    scale = size_scale(n_b, ref)
    X = np.ones((len(df), 1))
    wide_prior = np.array([np.nan])

    swing = (df.m_t - df.m_b).to_numpy()
    _, tau_swing = _fit_tau(X, swing, wide_prior, scale)
    turnout = np.log(df.n_t / df.n_b).to_numpy()
    _, tau_turnout = _fit_tau(X, turnout, wide_prior, scale)

    return HistoricalParams(
        tau_swing=tau_swing,
        tau_turnout=tau_turnout,
        systematic_swing=_systematic(X, swing, n_b, scale, tau_swing, wide_prior),
        systematic_turnout=_systematic(X, turnout, n_b, scale, tau_turnout, wide_prior),
        composition=_composition_prior(base, target),
        reference_votes=ref,
    )
