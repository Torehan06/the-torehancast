"""Print the on-expectation P(leader) path for each vote-type mode."""
import dataclasses

from torehancast.replay import harness, on_expectation
from torehancast.schema import ALL


def models():
    ga, _ = harness.build_model("GA", "primary")
    yield "split (GA)", ga, "split"
    fl, _ = harness.build_model("FL", "primary")
    yield "delta (FL)", fl, "delta"
    ga_all, _ = harness.build_model("GA", "primary")
    ga_all.baseline = ga_all.baseline.groupby("unit_id", as_index=False)[["D", "R"]].sum().assign(vote_type=ALL)
    ga_all.batch_vote_types = ()
    yield "all (GA collapsed)", ga_all, "all"


if __name__ == "__main__":
    for label, model, mode in models():
        steps = on_expectation.run(model, mode)
        path = " ".join(f"{s.p_leader:.3f}" for s in steps)
        dips = [round(b.p_leader - a.p_leader, 4) for a, b in zip(steps, steps[1:]) if b.p_leader < a.p_leader - 0.005]
        print(f"{label:20s} {path}\n{'':20s} medians {' '.join(f'{s.median*100:+.2f}' for s in steps)}\n{'':20s} dips>0.5pt: {dips}")
