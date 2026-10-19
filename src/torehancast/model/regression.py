"""Gaussian regression with a county random effect — used for both swing and turnout.

Each observed cell i (county c, vote type v) gives a value y_i:

    y_i = x_i · θ + ε_c + δ_i

    θ    ~ N(prior_mean, prior_cov)                     statewide effects
    ε_c  ~ N(0, (tau_county · county_scale_c)²)         county effect, shared by its vote types
    δ_i  ~ N(0, (tau_cell · cell_scale_i)² / ω_i)       cell noise; ω_i < 1 when partly reported

The scales let small counties be noisier than big ones (see `size_scale`).
Fitting is closed-form (generalised least squares with a conjugate prior).
Prediction draws θ, then each county's ε given that county's observed residuals,
then fresh cell noise. Everything is vectorised over draws.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Swing variance falls with county size roughly like size^-1/2; sd like size^-1/4.
SIZE_EXPONENT = 0.25


def size_scale(votes: np.ndarray, reference: float) -> np.ndarray:
    """Relative noise sd for units of a given size (1.0 at the reference size)."""
    return (reference / np.maximum(votes, 1.0)) ** SIZE_EXPONENT


@dataclass
class Priors:
    mean: np.ndarray  # (k,)
    cov: np.ndarray  # (k, k)
    tau_county: float
    tau_cell: float


class CountyEffectRegression:
    def __init__(self, priors: Priors, county_scale: np.ndarray):
        self.p = priors
        self.county_var = (priors.tau_county * county_scale) ** 2  # (n_counties,)
        self.n_counties = len(county_scale)

    def fit(
        self, X: np.ndarray, y: np.ndarray, county: np.ndarray, weight: np.ndarray, cell_scale: np.ndarray
    ) -> None:
        """X (n, k), y (n,), county (n,) ids, weight ω (n,) in (0, 1], cell_scale (n,)."""
        self.X, self.y, self.county = X, y, county
        prior_precision = np.linalg.inv(self.p.cov)
        # Inverse cell-noise variances, and per-county posterior variance of ε.
        self._d = weight / (self.p.tau_cell * cell_scale) ** 2
        s = np.bincount(county, weights=self._d, minlength=self.n_counties)
        self._shrink = 1.0 / (1.0 / self.county_var + s)
        if len(y) == 0:
            self.theta_mean, self.theta_cov = self.p.mean, self.p.cov
            return

        def vinv(M: np.ndarray) -> np.ndarray:
            # V⁻¹M for block-diagonal V_c = var_c·11ᵀ + D_c⁻¹ (Woodbury, county by county).
            DM = self._d[:, None] * M
            sums = np.zeros((self.n_counties, M.shape[1]))
            np.add.at(sums, county, DM)
            return DM - self._d[:, None] * (self._shrink[county][:, None] * sums[county])

        precision = prior_precision + X.T @ vinv(X)
        self.theta_cov = np.linalg.inv(precision)
        self.theta_cov = (self.theta_cov + self.theta_cov.T) / 2
        self.theta_mean = self.theta_cov @ (prior_precision @ self.p.mean + X.T @ vinv(y[:, None])[:, 0])

    def draw(
        self,
        rng: np.random.Generator,
        n: int,
        X_new: np.ndarray,
        county_new: np.ndarray,
        cell_scale_new: np.ndarray,
        add_cell_noise: bool = True,
    ) -> np.ndarray:
        """(n, m) predictive draws of y for m new cells.

        With `add_cell_noise=False` this predicts the underlying value x·θ + ε_c
        rather than a fresh noisy observation of it.
        """
        theta = rng.multivariate_normal(self.theta_mean, self.theta_cov, size=n)  # (n, k)

        eps_mean = np.zeros((n, self.n_counties))
        if len(self.y):
            resid = self.y[None, :] - theta @ self.X.T  # (n, obs)
            weighted = np.zeros((self.n_counties, n))
            np.add.at(weighted, self.county, (self._d[None, :] * resid).T)
            eps_mean = weighted.T * self._shrink[None, :]
        eps = eps_mean + np.sqrt(self._shrink)[None, :] * rng.standard_normal((n, self.n_counties))

        out = theta @ X_new.T + eps[:, county_new]
        if add_cell_noise:
            out += (self.p.tau_cell * cell_scale_new)[None, :] * rng.standard_normal((n, len(county_new)))
        return out
