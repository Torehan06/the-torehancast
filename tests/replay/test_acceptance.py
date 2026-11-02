"""A state goes live only when its replays pass these checks.

Run one state:  pytest tests/replay --state GA
Run one race:   pytest tests/replay --race 2026-IA-H01
Seeds:          REPLAY_SEEDS=50 pytest tests/replay   (default 20)

Two kinds of arrival order, held to different standards:
  * Realistic orders (random, and timezone where a state has late-closing units)
    are what election night can actually look like. They must meet the coverage,
    sharpness and bad-prior checks below.
  * Adversarial orders (d_first, r_first, ed_first) are deliberately unfair: whole
    blocs of one party's counties first. They only have to avoid confident wrong
    calls (P(wrong winner) < 0.95). Coverage under them is reported, not required.
  Orders that are legally impossible in a state are listed in IMPOSSIBLE_ORDERS.

These thresholds define "sensible output" (decided Oct 19, after all eight replays):
  * Coverage has a floor but no ceiling. Replaying ONE election under many arrival
    orders can't tell "honest but lucky" from "too wide" (every replay shares the
    same truth), so over-coverage is capped by width at 90% counted instead. Every
    pair clears the floors with room (80%: 0.96–1.00; 95%: 0.99–1.00), and the
    widest 80% band at 90% counted is 1.37 pts against the 3-pt cap.
  * Adversarial orders only need to avoid confident wrong calls (P(wrong) < 0.95);
    they're designed to be unfair.
  * A prior that is 8 points wrong must be overridden by the data by half-way,
    measured as 95% coverage at ≥ 50% counted over SEEDS nights (floor 0.90, like
    COVERAGE_95_MIN). It used to be "no miss in 3 seeds", which a calibrated 95%
    interval fails by chance: Florida failed it at 0.967 coverage over 20 seeds.
Tightening the coverage floor or the width cap trades robustness for sharpness.
"""

from __future__ import annotations

import math
import os

import numpy as np
import pytest

from torehancast.replay import harness

COVERAGE_80_MIN = 0.70
COVERAGE_95_MIN = 0.90
MAX_WIDTH_80_AT_90PCT = 0.03  # 3 pts
MAX_P_WRONG_ADVERSARIAL = 0.95
BAD_PRIOR_SHIFT = 0.08
BAD_PRIOR_COVERAGE_95_MIN = 0.90
START_TOLERANCE = 0.015  # 0% reporting median vs prior (MC noise + nonlinearity)
END_TOLERANCE = 0.001

SEEDS = int(os.environ.get("REPLAY_SEEDS", "20"))
# (key, pair): key is a state (config/replay.yaml) or a House race ID (config/house/).
PAIRS = [(key, pair) for key in harness.replay_keys() for pair in harness.PAIRS if pair in harness.replay_config(key)]
pytestmark = pytest.mark.replay


def _ids(p):
    return f"{p[0]}-{p[1]}"


def realistic_orders(key: str) -> list[str]:
    """random everywhere; timezone only where some units close later."""
    profile = harness.replay_config(key).get("arrival_profile", {})
    return ["random"] + (["timezone"] if profile.get("late_close") else [])


@pytest.fixture(scope="module", params=PAIRS, ids=_ids)
def random_replays(request):
    """Every realistic order × SEEDS nights (named for history: not just random)."""
    state, pair = request.param
    return state, pair, [
        harness.run(state, pair, order, s, n_draws=2000) for order in realistic_orders(state) for s in range(SEEDS)
    ]


def test_starts_at_the_prior(random_replays):
    state, pair, replays = random_replays
    prior = harness.replay_config(state)[pair]["prior"]
    assert abs(replays[0].start.margin_median - prior["margin"]) < START_TOLERANCE


def test_ends_at_the_official_result(random_replays):
    _, _, replays = random_replays
    for r in replays:
        assert abs(r.end.margin_median - r.truth_margin) < END_TOLERANCE
        winner = "D" if r.truth_margin > 0 else "R"
        assert r.end.p_win[winner] > 0.99


def test_interval_coverage(random_replays):
    _, _, replays = random_replays
    in80 = [c.result.margin_80[0] <= r.truth_margin <= c.result.margin_80[1] for r in replays for c in r.checkpoints]
    in95 = [c.result.margin_95[0] <= r.truth_margin <= c.result.margin_95[1] for r in replays for c in r.checkpoints]
    assert np.mean(in80) >= COVERAGE_80_MIN, f"80% coverage {np.mean(in80):.2f}"
    assert np.mean(in95) >= COVERAGE_95_MIN, f"95% coverage {np.mean(in95):.2f}"


def test_intervals_are_sharp_late(random_replays):
    _, _, replays = random_replays
    widths = [c.result.margin_80[1] - c.result.margin_80[0] for r in replays for c in r.checkpoints if c.share >= 0.9]
    assert np.mean(widths) < MAX_WIDTH_80_AT_90PCT, f"mean 80% width at 90% counted {np.mean(widths) * 100:.1f} pts"


# Orders that cannot happen in a state, and why. Excluded only with a legal reason.
IMPOSSIBLE_ORDERS = {
    # Florida law has counties post early and mail ballots before any precinct
    # reports (and the feed's vote-type split is inferred from exactly that), so
    # Election Day votes can never arrive first.
    ("FL", "ed_first"),
}


@pytest.mark.parametrize("pair_id", PAIRS, ids=_ids)
@pytest.mark.parametrize("order", ["d_first", "r_first", "ed_first"])
def test_no_confident_wrong_call_under_adversarial_orders(pair_id, order):
    state, pair = pair_id
    if (harness.state_of(state), order) in IMPOSSIBLE_ORDERS:
        pytest.skip(f"{order} is impossible in {state} (see IMPOSSIBLE_ORDERS)")
    for seed in range(3):
        r = harness.run(state, pair, order, seed, n_draws=2000)
        wrong = "R" if r.truth_margin > 0 else "D"
        worst = max(c.result.p_win[wrong] for c in r.checkpoints)
        assert worst < MAX_P_WRONG_ADVERSARIAL, f"{order} seed {seed}: P(wrong) {worst:.3f}"


@pytest.mark.parametrize("pair_id", PAIRS, ids=_ids)
def test_data_overrides_a_bad_prior(pair_id):
    state, pair = pair_id
    truth = harness.run(state, pair, "random", 0, n_draws=200).truth_margin
    shift = -BAD_PRIOR_SHIFT if truth > 0 else BAD_PRIOR_SHIFT  # push toward the loser
    covered, misses = [], []
    for seed in range(SEEDS):
        r = harness.run(state, pair, "random", seed, n_draws=2000, prior_shift=shift)
        for c in r.checkpoints:
            if c.share >= 0.5:
                lo, hi = c.result.margin_95
                covered.append(lo <= truth <= hi)
                if not covered[-1]:
                    misses.append(f"seed {seed} at {c.share:.0%}: [{lo:+.3f}, {hi:+.3f}]")
    assert np.mean(covered) >= BAD_PRIOR_COVERAGE_95_MIN, f"coverage {np.mean(covered):.2f}; misses: {misses}"


def test_result_json_is_well_formed(random_replays):
    _, _, replays = random_replays
    d = replays[0].checkpoints[0].result.to_dict()
    assert set(d) >= {"p_win", "margin", "reported_votes", "expected_votes", "share_counted", "warnings"}
    assert math.isclose(d["p_win"]["D"] + d["p_win"]["R"], 1.0)
    assert all(math.isfinite(x) for x in (d["margin"]["median"], *d["margin"]["p80"], *d["margin"]["p95"]))
