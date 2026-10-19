"""For a state's bad-prior replays: band, truth, and prior vs data share at ≥ 50% counted.

    python scripts/prior_influence.py FL primary
"""
import sys

from torehancast.adapters.fl_dos import BatchTracker
from torehancast.replay import arrivals, harness

state, pair = sys.argv[1], sys.argv[2]
SHIFT = 0.08
cfg = harness.replay_config(state)
delta = cfg.get("vote_split") == "delta"


def night(seed, shift):
    model, spec = harness.build_model(state, pair, shift)
    final = harness.final_result(state, spec["target"])
    tot = final.totals()
    two = tot["D"] + tot["R"]
    truth = (tot["D"] - tot["R"]) / two
    if delta:
        final = arrivals.synthesize_modes(final, seed)
        events = arrivals.timeline(final, "random", seed, arrivals.Profile(batch_types=("early",), late_types=()))
        tracker = BatchTracker()
    else:
        events = arrivals.timeline(final, "random", seed)
    out, pending = [], list(harness.CHECKPOINTS)
    for t, snap in arrivals.snapshots(final, events):
        counted = sum(c.votes.get("D", 0) + c.votes.get("R", 0) for c in snap.cells) / two
        if delta:
            snap = tracker.split(arrivals.flatten(snap))
        if pending and counted >= pending[0]:
            r = model.run(snap, 2000, seed)
            out.append((counted, r, model.last_data_weight))
            while pending and counted >= pending[0]:
                pending.pop(0)
    return truth, out


print(f"{state} {pair}: wrong prior shifted {SHIFT*100:.0f} pts toward the loser")
print("seed  counted   truth   95% band (wrong prior)      miss   median wrong/right   pull   data:prior   prior share")
for seed in range(3):
    truth, good = night(seed, 0.0)
    shift = -SHIFT if truth > 0 else SHIFT
    _, bad = night(seed, shift)
    for (cg, rg, _), (cb, rb, dw) in zip(good, bad):
        if cb < 0.5:
            continue
        lo, hi = rb.margin_95
        miss = 0.0 if lo <= truth <= hi else min(abs(truth - lo), abs(truth - hi))
        pull = rb.margin_median - rg.margin_median
        print(f"{seed:4d}  {cb:6.0%}  {truth*100:+6.2f}   [{lo*100:+6.2f}, {hi*100:+6.2f}]   {'MISS ' + format(miss*100, '.2f') if miss else 'ok':>9}"
              f"   {rb.margin_median*100:+6.2f} / {rg.margin_median*100:+6.2f}   {pull*100:+5.2f}   {dw:7.1f}:1   {1/(1+dw):6.1%}")
