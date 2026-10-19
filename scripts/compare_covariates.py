"""Do the ACS covariates help? Accuracy and sharpness, not just coverage.

For each state's realistic orders, at 25/50/75% counted: median absolute error of
the median margin, mean 80% band width, and 80% / 95% coverage, for

  acs        ACS covariates in tonight's regression (current)
  no_acs     same model, no ACS covariates (partisanship and size only)
  tau_pz     ACS on, but τ keeps credit for partisanship + size (the first prototype)

    python scripts/compare_covariates.py [seeds]
"""

import sys

import numpy as np

from torehancast.model import tau as tau_module
from torehancast.replay import harness

SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 20
STATES = [("GA", "primary"), ("GA", "secondary"), ("NC", "primary"), ("FL", "primary")]
CHECKS = (0.25, 0.50, 0.75)


def orders(state):
    late = harness.replay_config(state).get("arrival_profile", {}).get("late_close")
    return ["random"] + (["timezone"] if late else [])


def variant(name):
    """Configure the model for one variant (patches are undone by the next call)."""
    harness._params.cache_clear()
    real_estimate = tau_module.__dict__.setdefault("_real_estimate", tau_module.estimate)
    tau_module.estimate = real_estimate
    harness.build_model = harness.__dict__.setdefault("_real_build", harness.build_model)
    if name == "no_acs":
        real_build = harness.build_model

        def build(*a, **k):
            m, spec = real_build(*a, **k)
            m.demographics = None
            return m, spec

        harness.build_model = build
    if name == "tau_pz":
        from torehancast.model.swing import covariates, design

        def estimate(base, target):
            p = real_estimate(base, target)
            b, t = tau_module.county_table(base), tau_module.county_table(target)
            df = b.merge(t, on="unit_id", suffixes=("_b", "_t"))
            df = df[(df.n_b > 0) & (df.n_t > 0)]
            n_b = df.n_b.to_numpy(float)
            scale = tau_module.size_scale(n_b, float(np.median(n_b)))
            X, sds = design(covariates(df.unit_id.to_numpy(), df.m_b.to_numpy(), n_b, None), n_b)
            swing = (df.m_t - df.m_b).to_numpy()
            _, tau_s = tau_module._fit_tau(X, swing, sds, scale)
            return tau_module.HistoricalParams(tau_s, p.tau_turnout,
                                               tau_module._systematic(X, swing, n_b, scale, tau_s, sds),
                                               p.systematic_turnout, p.composition, p.reference_votes)

        tau_module.estimate = estimate


def measure(state, pair):
    rows = {c: [] for c in CHECKS}
    for order in orders(state):
        for seed in range(SEEDS):
            r = harness.run(state, pair, order, seed, n_draws=2000)
            for c in CHECKS:
                cp = next(x for x in r.checkpoints if x.share >= c - 1e-9)
                res = cp.result
                rows[c].append((abs(res.margin_median - r.truth_margin), res.margin_80[1] - res.margin_80[0],
                                res.margin_80[0] <= r.truth_margin <= res.margin_80[1],
                                res.margin_95[0] <= r.truth_margin <= res.margin_95[1]))
    return {c: np.array(v, dtype=float).mean(axis=0) for c, v in rows.items()}


if __name__ == "__main__":
    print(f"{SEEDS} seeds per realistic order; MAE and width in points of two-party margin")
    print(f"{'state':14s} {'variant':8s} " + "  ".join(f"{int(c*100):>2d}%: MAE  width  cov80 cov95" for c in CHECKS))
    for state, pair in STATES:
        for name in ("acs", "no_acs", "tau_pz"):
            variant(name)
            m = measure(state, pair)
            cells = "  ".join(f"     {m[c][0]*100:4.2f}  {m[c][1]*100:5.2f}  {m[c][2]:.2f}  {m[c][3]:.2f}" for c in CHECKS)
            print(f"{state + ' ' + pair:14s} {name:8s} {cells}")
    variant("acs")
