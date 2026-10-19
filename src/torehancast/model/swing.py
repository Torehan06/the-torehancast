"""The swing regression's design, and how much a partly counted county is trusted."""

from __future__ import annotations

import numpy as np

from ..schema import ALL

# A partly counted county in a state without a vote-type split mixes ballot types
# that lean differently and arrive in different orders, so its partial margin is
# biased until most of it is in (FL/MN mail dumps).
ALL_PARTIAL_SD = 0.06  # sd of that bias for a county half counted
ALL_CELL_TAU_INFLATION = 1.25  # extra width on top, for states without a split

# A partly counted cell's margin differs from where the cell will finish because
# precincts differ: sd ≈ PRECINCT_SD · sqrt((1 − f) / f) at fraction f counted.
# Measured on NC 2024 Election Day precincts with precincts drawn in random order
# (14 pts at f = 0.25, 8 at 0.5, 4.5 at 0.75). Real reporting order isn't random,
# so treat this as a floor.
PRECINCT_SD = 0.08

# County covariates: baseline partisanship, size, and ACS demographics. Each is
# standardised (vote-weighted mean 0, sd 1 across the state's units), so one prior
# sd means the same thing for all of them.
DEMOGRAPHIC_COLUMNS = ("white_nh", "black_nh", "asian_nh", "hispanic", "median_income", "bachelors_plus", "median_age")
TURNOUT_COVARIATES = ("partisanship", "log_size")

# TODO(torehan): how far a covariate may move swing. Default: 1 pt of swing per
# 1 sd of the covariate (prior sd 0.01), zero-centred. Tight on purpose: the first
# few counties in are rarely representative, so they shouldn't be able to say
# "college-educated counties are swinging 5 pts" on their own. Looser lets the model
# exploit real demographic patterns sooner, at the risk of chasing early noise.
# Unreported counties share these coefficients, so their errors move together.
COVARIATE_PRIOR_SD = 0.01
TURNOUT_COVARIATE_PRIOR_SD = 0.03  # log turnout ratio per 1 sd


def covariates(
    unit_id: np.ndarray, baseline_margin: np.ndarray, county_votes: np.ndarray, demographics=None
) -> dict[str, np.ndarray]:
    """Raw covariate values per unit. Units missing from the demographics file get the mean."""
    out = {"partisanship": baseline_margin, "log_size": np.log(np.maximum(county_votes, 1.0))}
    if demographics is not None:
        demo = demographics.set_index("unit_id")
        for col in DEMOGRAPHIC_COLUMNS:
            if col in demo:
                values = demo[col].reindex(unit_id).to_numpy(dtype=float)
                out[col] = np.where(np.isnan(values), np.nanmean(values), values)
    return out


def design(covariates: dict[str, np.ndarray], votes: np.ndarray, prior_sd: float = COVARIATE_PRIOR_SD):
    """Design matrix [1, standardised covariates...] and matching prior sds.

    Centring on the vote-weighted mean makes the intercept the statewide swing, so its
    prior is simply "your margin − baseline margin" (filled in by the caller: NaN here).
    """
    cols, sds = [np.ones(len(votes))], [np.nan]
    for values in covariates.values():
        sd = np.std(values)
        if sd < 1e-9:
            continue
        cols.append((values - np.average(values, weights=votes)) / sd)
        sds.append(prior_sd)
    return np.column_stack(cols), np.array(sds)


def turnout_design(covariates: dict[str, np.ndarray], votes: np.ndarray):
    return design({k: covariates[k] for k in TURNOUT_COVARIATES}, votes, TURNOUT_COVARIATE_PRIOR_SD)


def measurement_sd(counted_share: np.ndarray, sigma: float, split: bool) -> np.ndarray:
    """How uncertain is a partly counted county's implied final value?

    `counted_share` P is the fraction of the county's expected final vote already
    in, and `sigma` is the composition noise for this quantity (gap or share).

    TODO(torehan): this is the main judgement call in the model. Defaults:
      * split states: sd = sigma · (1 − P) / P. Half counted → 1·sigma, 90% → 0.11·sigma.
        Error comes only from not knowing how the missing vote types lean.
      * `all` states: sd = ALL_PARTIAL_SD · (1 − P) / P², a steeper curve, so the
        county's swing is "down-weighted until it's mostly reported".
    Trade-offs: steeper curves protect against early-batch bias but make the model
    slower to react on election night. Check changes against the replay
    adversarial orders (tests/replay), especially "election day first".
    """
    P = np.clip(counted_share, 0.02, 1.0)
    if split:
        sd = sigma * (1.0 - P) / P
    else:
        sd = ALL_PARTIAL_SD * (1.0 - P) / P**2
    return np.maximum(sd, 1e-4)
