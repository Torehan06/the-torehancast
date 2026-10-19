"""Coverage of the model's intervals across many synthetic election nights.

    python scripts/coverage.py GA primary 30
"""
import sys
import time

import numpy as np

from torehancast.replay import harness

state, pair, n_seeds = sys.argv[1], sys.argv[2], int(sys.argv[3])
t0 = time.time()
rows = []
for order in ("random", "d_first", "r_first", "ed_first"):
    seeds = range(n_seeds) if order == "random" else range(max(n_seeds // 5, 3))
    for seed in seeds:
        r = harness.run(state, pair, order, seed, n_draws=2000)
        for c in r.checkpoints:
            lo80, hi80 = c.result.margin_80
            lo95, hi95 = c.result.margin_95
            wrong = c.result.p_win["R" if r.truth_margin > 0 else "D"]
            rows.append((order, c.share, lo80 <= r.truth_margin <= hi80, lo95 <= r.truth_margin <= hi95, wrong, hi80 - lo80))
rows = np.array(rows, dtype=object)
for order in ("random", "d_first", "r_first", "ed_first"):
    m = rows[:, 0] == order
    print(f"{order:9s} n={m.sum():3d}  80% cover {rows[m, 2].mean():.2f}  95% cover {rows[m, 3].mean():.2f}"
          f"  max P(wrong) {max(rows[m, 4]):.3f}  mean 80% width {np.mean(rows[m, 5].astype(float)) * 100:.1f} pts")
for cp in harness.CHECKPOINTS:
    m = (rows[:, 0] == "random") & (np.abs(rows[:, 1].astype(float) - cp) < 0.12)
    if m.any():
        print(f"  random ~{cp:.0%}: 80% {rows[m, 2].mean():.2f}  95% {rows[m, 3].mean():.2f}")
print(f"{time.time() - t0:.0f}s")
