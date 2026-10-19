"""When every batch lands exactly where the model projected, confidence in the
projected leader may only grow (within 0.5 pts of Monte Carlo noise).

One test per way states report vote types: per-type cells (GA), Florida's
snapshot-delta inference, and down-weighted `all` cells (GA collapsed).
"""

from __future__ import annotations

import pytest

from torehancast.replay import harness, on_expectation
from torehancast.schema import ALL

TOLERANCE = 0.005
pytestmark = pytest.mark.replay


def _model(mode: str):
    if mode == "split":
        return harness.build_model("GA", "primary")[0]
    if mode == "delta":
        return harness.build_model("FL", "primary")[0]
    model = harness.build_model("GA", "primary")[0]
    model.baseline = model.baseline.groupby("unit_id", as_index=False)[["D", "R"]].sum().assign(vote_type=ALL)
    model.batch_vote_types = ()
    return model


@pytest.mark.parametrize("mode", ["split", "delta", "all"])
def test_p_leader_never_falls_on_expectation(mode):
    steps = on_expectation.run(_model(mode), mode)
    for before, after in zip(steps, steps[1:]):
        assert after.p_leader >= before.p_leader - TOLERANCE, (
            f"{mode}: P(leader) fell {before.p_leader:.3f} → {after.p_leader:.3f} at {after.share_counted:.0%} counted"
        )
    assert steps[-1].p_leader > 0.99
