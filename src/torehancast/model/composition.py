"""Within-county vote-type composition, learned from tonight's complete counties.

For a county whose early and mail votes are in but Election Day isn't, two
questions decide what's left:

  share  how big a part of the county's final vote is each vote type?
  gap    how far does each vote type's margin sit from the county's overall margin?

Both start from the county's own baseline composition and are shifted by
statewide, per-vote-type adjustments learned from counties that have finished
counting tonight:

  share_cv ∝ baseline_share_cv · exp(α_v + α'_v · z_c)    (normalised to sum to 1)
  gap_cv   = baseline_gap_cv + g_v + g'_v · z_c           (re-centred so Σ share·gap = 0)

where z_c is the county's standardised log size: in 2024, metro Election Day votes
moved much further from their county's margin than rural ones did, and the slope
lets tonight's data say so. Its uncertainty is shared by every big county.

Learning α and g live, rather than trusting the baseline split, is what keeps a
shift like Georgia's 2020 → 2022 (mail voters returning to early in-person)
from wrecking the estimate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FLOOR = 1e-4
MAJOR_SHARE = 0.02  # vote types smaller than this don't block learning from a county
# Partial cells are weighted by 1 / (1 + c·(1 − f)/f), which falls smoothly to 0 as the
# counted fraction f → 0, so no hard cut-off is needed (a cut-off would make the model
# jump when a cell crosses it). This floor only avoids dividing by zero.
MIN_MEASURED = 1e-3
# Counties' composition quirks are correlated (big counties' late precincts tend to
# lean the same way), so 159 counties are not 159 independent pieces of evidence.
# The fit never claims more than this many. Chosen after the GA 2022 → 2024 replay
# learned the Election Day gap to ±0.9 pts and missed by 3.3.
MAX_EFFECTIVE_COUNTIES = 15.0
# Extra noise in a partly counted cell's share and gap (precinct heterogeneity),
# scaled by (1 − f) / f. The gap value matches swing.PRECINCT_SD.
PARTIAL_GAP_SD = 0.08
PARTIAL_SHARE_SD = 0.15
SLOPE_PRIOR_RATIO = 0.5  # prior sd of the size slopes, relative to the intercepts'


@dataclass(frozen=True)
class CompositionPrior:
    shift_sd: float  # prior sd of α_v (log share shift per vote type)
    share_sd: float  # county noise around the predicted log share
    gap_shift_sd: float  # prior sd of g_v (gap shift per vote type)
    gap_sd: float  # county noise around the predicted gap


def baseline(b_votes: np.ndarray, b_diff: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(counties, types) baseline shares and gaps from baseline two-party votes and D−R."""
    total = b_votes.sum(axis=1, keepdims=True)
    share = np.maximum(b_votes / np.maximum(total, 1), FLOOR)
    share /= share.sum(axis=1, keepdims=True)
    county_margin = b_diff.sum(axis=1, keepdims=True) / np.maximum(total, 1)
    margin = np.where(b_votes > 0, b_diff / np.maximum(b_votes, 1), county_margin)
    return share, margin - county_margin


class Composition:
    def __init__(self, prior: CompositionPrior, base_share: np.ndarray, base_gap: np.ndarray, size: np.ndarray):
        """`size`: per-county baseline votes (used for the size slope)."""
        self.prior = prior
        self.base_share, self.base_gap = base_share, base_gap
        log_size = np.log(np.maximum(size, 1.0))
        sd = np.std(log_size)
        self.z = (log_size - np.average(log_size, weights=size)) / (sd if sd > 1e-9 else 1.0)
        k = base_share.shape[1]
        # Per vote type: [intercept, size slope] means and 2×2 covariances.
        self.alpha, self.alpha_cov = np.zeros((k, 2)), np.tile(self._prior_cov(prior.shift_sd), (k, 1, 1))
        self.g, self.g_cov = np.zeros((k, 2)), np.tile(self._prior_cov(prior.gap_shift_sd), (k, 1, 1))

    @staticmethod
    def _prior_cov(sd: float) -> np.ndarray:
        return np.diag([sd**2, (SLOPE_PRIOR_RATIO * sd) ** 2])

    def fit(self, measured: np.ndarray, votes: np.ndarray, diff: np.ndarray) -> None:
        """Learn the shifts from counties whose major vote types have a *measured* completion.

        `measured` is a (counties, types) array: 1.0 for finished cells, the precinct
        fraction for partly counted cells whose fraction the feed reports, and 0 where
        unknown. Partial cells are scaled up to a full-cell estimate and count for less,
        so learning starts long before any county finishes. Types under MAJOR_SHARE of a
        county's baseline never block it.
        """
        major = self.base_share >= MAJOR_SHARE
        usable = np.all((measured >= MIN_MEASURED) | ~major, axis=1) & (votes.sum(axis=1) > 0)
        if not usable.any():
            return
        e = measured[usable]
        ok = (e >= MIN_MEASURED) & (votes[usable] > 0)
        scale = np.where(ok, 1.0 / np.maximum(e, MIN_MEASURED), 0.0)
        v, d = votes[usable] * scale, diff[usable] * scale  # estimated full cells
        total = v.sum(axis=1, keepdims=True)
        share = np.maximum(v / total, FLOOR)
        margin_c = d.sum(axis=1, keepdims=True) / total
        gap = np.where(v > 0, d / np.maximum(v, 1), margin_c) - margin_c

        # Log share shift vs baseline, with each county's normaliser removed (over used cells).
        log_shift = np.log(share) - np.log(self.base_share[usable])
        n_ok = np.maximum(ok.sum(axis=1, keepdims=True), 1)
        log_shift -= np.where(ok, log_shift, 0).sum(axis=1, keepdims=True) / n_ok
        gap_shift = gap - self.base_gap[usable]

        X = np.column_stack([np.ones(usable.sum()), self.z[usable]])
        partial = np.clip((1.0 - e) / np.maximum(e, MIN_MEASURED), 0.0, None)
        for name, noise, extra, data, prior_sd in (
            ("alpha", self.prior.share_sd, PARTIAL_SHARE_SD, log_shift, self.prior.shift_sd),
            ("g", self.prior.gap_sd, PARTIAL_GAP_SD, gap_shift, self.prior.gap_shift_sd),
        ):
            # Precision weights: a finished cell counts fully, a partial one less.
            w = np.where(ok, 1.0 / (1.0 + (extra / noise) ** 2 * partial), 0.0)
            # Cap the evidence at MAX_EFFECTIVE_COUNTIES worth of finished counties.
            w = w * np.minimum(1.0, MAX_EFFECTIVE_COUNTIES / np.maximum(w.sum(axis=0), 1e-9))
            prior_precision = np.linalg.inv(self._prior_cov(prior_sd))
            mean, cov = getattr(self, name).copy(), getattr(self, f"{name}_cov").copy()
            for j in range(data.shape[1]):
                # Conjugate normal regression on [1, z] with known county noise.
                wj = w[:, j] / noise**2
                post_cov = np.linalg.inv(prior_precision + (X * wj[:, None]).T @ X)
                mean[j] = post_cov @ (X.T @ (wj * np.where(ok[:, j], data[:, j], 0.0)))
                cov[j] = post_cov
            setattr(self, name, mean)
            setattr(self, f"{name}_cov", cov)

    def _per_county(self, coef: np.ndarray) -> np.ndarray:
        """(types, 2) coefficients → (counties, types) shifts."""
        return coef[None, :, 0] + self.z[:, None] * coef[None, :, 1]

    def predicted(self, alpha_shift=None, g_shift=None) -> tuple[np.ndarray, np.ndarray]:
        """(share, gap) for every county and vote type."""
        a = self._per_county(self.alpha) if alpha_shift is None else alpha_shift
        g = self._per_county(self.g) if g_shift is None else g_shift
        share = self.base_share * np.exp(a)
        share /= share.sum(axis=1, keepdims=True)
        gap = self.base_gap + g
        gap -= (share * gap).sum(axis=1, keepdims=True)
        return share, gap
