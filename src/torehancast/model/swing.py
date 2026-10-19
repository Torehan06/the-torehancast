"""The swing regression's design, and how much a partly counted county is trusted."""

from __future__ import annotations

import numpy as np

from ..schema import ALL

# A partly counted county in a state without a vote-type split mixes ballot types
# that lean differently and arrive in different orders, so its partial margin is
# biased until most of it is in (FL/MN mail dumps).
ALL_PARTIAL_SD = 0.06  # curve coefficient: sd = scale · 0.06 · (1 − P) / P², 0.24 when half counted
ALL_CELL_TAU_INFLATION = 1.25  # extra width on top, for states without a split
# Multiplies every partly counted county's measurement sd (see measurement_sd).
# Swept over all eight replay pairs (Oct 19); mean error of the median at ≤ 50%
# counted, in pts: ×0.5 1.57, ×1 1.45, ×1.5 1.36, ×2 1.32, ×3 1.36. Every scale
# from ×1 up passes acceptance; ×2 also lifts 80% coverage in every state (AK
# 0.90 → 0.97) and cuts AK's worst adversarial P(wrong) from 0.82 to 0.60. Cost:
# the 80% band at 90% counted widens by 0.1–0.4 pts (max 1.4, cap 3).
PARTIAL_SD_SCALE = 2.0

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

# How far a covariate may move swing: 1 pt of swing per 1 sd of the covariate
# (prior sd 0.01), zero-centred. Tight on purpose: the first few counties in are
# rarely representative, so they shouldn't be able to say "college-educated
# counties are swinging 5 pts" on their own. Unreported counties share these
# coefficients, so their errors move together. Swept over all eight replay pairs
# (Oct 19): 0.005 and 0.02 pass too, but neither wins. 0.005 trims mean error at
# ≤ 50% counted (1.39 vs 1.45 pts) while dropping NC's 80% coverage to 0.86 and
# raising GA's worst adversarial P(wrong) to 0.77; 0.02 is worse in 5 of 8 pairs.
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

    The main judgement call in the model:
      * split states: sd = PARTIAL_SD_SCALE · sigma · (1 − P) / P. Half counted →
        2·sigma, 90% → 0.22·sigma. Error comes only from not knowing how the missing
        vote types lean.
      * `all` states: sd = PARTIAL_SD_SCALE · ALL_PARTIAL_SD · (1 − P) / P², a
        steeper curve, so the county's swing is "down-weighted until it's mostly
        reported".
    Steeper curves protect against early-batch bias but make the model slower to
    react. See PARTIAL_SD_SCALE for how the scale was chosen.
    """
    P = np.clip(counted_share, 0.02, 1.0)
    if split:
        sd = sigma * (1.0 - P) / P
    else:
        sd = ALL_PARTIAL_SD * (1.0 - P) / P**2
    return np.maximum(PARTIAL_SD_SCALE * sd, 1e-4)
