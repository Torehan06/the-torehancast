"""Break a replay checkpoint down by county status: expected vs actual."""
import sys

from torehancast import elections as E
from torehancast.model.tau import county_table
from torehancast.replay import arrivals, harness

state, order, seed, target_share = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
pair = sys.argv[5] if len(sys.argv) > 5 else "primary"
model, spec = harness.build_model(state, pair)
final = E.final_snapshot(E.load(state, spec["target"]))
truth = county_table(E.read_baseline(state, spec["target"]))[["unit_id", "n", "D", "R"]]
tot = final.totals(); two = tot["D"] + tot["R"]
for t, snap in arrivals.snapshots(final, arrivals.timeline(final, order, seed)):
    counted = sum(c.votes.get("D", 0) + c.votes.get("R", 0) for c in snap.cells) / two
    if counted >= target_share:
        break
res = model.run(snap, 4000, seed)
lc = model.last_counties.merge(truth, on="unit_id")
lc["exp_diff"] = lc.expected_votes * lc.expected_margin
lc["act_diff"] = lc.D - lc.R
print(f"counted {counted:.0%}  model median {res.margin_median*100:+.2f}  truth {(tot['D']-tot['R'])/two*100:+.2f}")
g = lc.groupby("status").agg(counties=("unit_id", "count"), expected=("expected_votes", "sum"), actual=("n", "sum"),
                             exp_diff=("exp_diff", "sum"), act_diff=("act_diff", "sum"), reported=("reported_votes", "sum"))
print(g.round(0).to_string())
part = lc[lc.status == "partial"].assign(err=lambda d: d.exp_diff - d.act_diff).sort_values("err", key=abs, ascending=False)
print(part.head(8)[["unit_id", "reported_votes", "expected_votes", "n", "reported_margin", "expected_margin", "err"]].round(3).to_string())
