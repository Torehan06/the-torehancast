"""What does the late-mail hazard cost Florida? Same nights with and without it.

Late mail slices arrive after a county's precincts start, so BatchTracker books
them as Election Day. Reports MAE, signed error (+ = too Democratic), 80% width
and coverage at 25/50/75/90% counted, plus the worst P(wrong winner).

    python scripts/late_mail_damage.py [seeds]
"""

import sys

import numpy as np

from torehancast.replay import harness

SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 20
CHECKS = (0.25, 0.50, 0.75, 0.90)

for label, overrides in (("with late mail", None), ("without late mail", {"late_mail": None})):
    rows = {c: [] for c in CHECKS}
    worst = 0.0
    for order in ("random", "timezone"):
        for seed in range(SEEDS):
            r = harness.run("FL", "primary", order, seed, n_draws=2000, profile_overrides=overrides)
            wrong = "D" if r.truth_margin < 0 else "R"
            worst = max([worst] + [c.result.p_win[wrong] for c in r.checkpoints])
            for c in CHECKS:
                res = next(x for x in r.checkpoints if x.share >= c - 1e-9).result
                err = res.margin_median - r.truth_margin
                rows[c].append((abs(err), err, res.margin_80[1] - res.margin_80[0],
                                res.margin_80[0] <= r.truth_margin <= res.margin_80[1],
                                res.margin_95[0] <= r.truth_margin <= res.margin_95[1]))
    print(f"FL {label}  (worst P(wrong winner) {worst:.3f})")
    for c in CHECKS:
        mae, signed, width, c80, c95 = np.array(rows[c], dtype=float).mean(axis=0)
        print(f"  {int(c*100):2d}%  MAE {mae*100:4.2f}  signed {signed*100:+5.2f}  80% width {width*100:5.2f}  cov80 {c80:.2f}  cov95 {c95:.2f}")
