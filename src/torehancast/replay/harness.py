"""Run a replay: synthetic election night → model → checkpoints.

    python -m torehancast.replay.harness --state GA --order random --seed 1
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import lru_cache

import yaml

from .. import demographics, elections
from ..model import tau
from ..model.simulate import RaceModel, RacePrior, Result
from ..adapters.fl_dos import BatchTracker
from . import arrivals

CHECKPOINTS = (0.10, 0.25, 0.50, 0.75, 0.90)


@dataclass
class Checkpoint:
    share: float  # share of the final two-party vote counted
    time: float
    result: Result


@dataclass
class Replay:
    state: str
    pair: str
    truth_margin: float  # final two-party D−R margin
    start: Result  # 0% reporting
    checkpoints: list[Checkpoint]
    end: Result  # 100% reporting


def replay_config(state: str) -> dict:
    return yaml.safe_load((elections.CONFIG / "replay.yaml").read_text())[state]


@lru_cache(maxsize=None)
def _params(state: str, a: str, b: str):
    return tau.estimate(elections.read_baseline(state, a), elections.read_baseline(state, b))


@lru_cache(maxsize=None)
def final_result(state: str, key: str):
    return elections.final_snapshot(elections.load(state, key))


def arrival_profile(cfg: dict, overrides: dict | None = None) -> arrivals.Profile:
    spec = dict(cfg.get("arrival_profile", {}))
    for key in ("batch_types", "chunked_types", "late_types"):
        if key in spec:
            spec[key] = tuple(spec[key])
    spec.update(overrides or {})
    return arrivals.Profile(**spec)


def build_model(state: str, pair: str = "primary", prior_shift: float = 0.0) -> tuple[RaceModel, dict]:
    cfg = replay_config(state)
    spec = cfg[pair]
    demo = demographics.load(state)
    params = _params(state, *spec["tau_pair"])
    prior = RacePrior(**spec["prior"])
    if prior_shift:
        prior = RacePrior(prior.margin + prior_shift, prior.margin_sd, prior.turnout_ratio, prior.turnout_sd)
    model = RaceModel(
        elections.read_baseline(state, spec["baseline"]),
        prior,
        params,
        batch_vote_types=tuple(cfg.get("batch_vote_types", ())),
        demographics=demo,
        synthetic_split=cfg.get("synthetic_split"),
    )
    return model, spec


def run(
    state: str,
    pair: str = "primary",
    order: str = "random",
    seed: int = 0,
    n_draws: int = 4000,
    prior_shift: float = 0.0,
    on_snapshot=None,
    profile_overrides: dict | None = None,
) -> Replay:
    """`on_snapshot(time, snapshot, result)` lets the publisher stream every step.

    `profile_overrides` replaces parts of the state's arrival profile, e.g.
    {"late_mail": None} to measure what the late-mail event costs.
    """
    model, spec = build_model(state, pair, prior_shift)
    final = final_result(state, spec["target"])
    totals = final.totals()
    two_party = totals["D"] + totals["R"]
    truth = (totals["D"] - totals["R"]) / two_party

    cfg = replay_config(state)
    profile = arrival_profile(cfg, profile_overrides)
    delta = cfg.get("vote_split") == "delta"
    if delta:  # Florida: archive has no vote types; invent them, then hide them again
        final = arrivals.synthesize_modes(final, seed)
        tracker = BatchTracker()
    events = arrivals.timeline(final, order, seed, profile)
    pending = list(CHECKPOINTS)
    checkpoints: list[Checkpoint] = []
    start = end = None
    for t, snap in arrivals.snapshots(final, events):
        counted = sum(c.votes.get("D", 0) + c.votes.get("R", 0) for c in snap.cells) / two_party
        if delta:
            snap = tracker.split(arrivals.flatten(snap))
        due = start is None or (pending and counted >= pending[0]) or counted >= 1.0 or on_snapshot
        if not due:
            continue
        result = model.run(snap, n_draws, seed)
        if on_snapshot:
            on_snapshot(t, snap, result)
        if start is None:
            start = result
        while pending and counted >= pending[0]:
            checkpoints.append(Checkpoint(counted, t, result))
            pending.pop(0)
        end = result
    return Replay(state, pair, truth, start, checkpoints, end)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--pair", default="primary")
    ap.add_argument("--order", default="random", choices=arrivals.ORDERS)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--prior-shift", type=float, default=0.0)
    args = ap.parse_args()
    r = run(args.state, args.pair, args.order, args.seed, prior_shift=args.prior_shift)
    print(f"{r.state} {r.pair} order={args.order} seed={args.seed} truth {r.truth_margin * 100:+.2f}")
    rows = [("start", 0.0, r.start)] + [(f"{c.share:.0%}", c.time, c.result) for c in r.checkpoints] + [("end", None, r.end)]
    for label, t, res in rows:
        lo, hi = res.margin_80
        lo95, hi95 = res.margin_95
        print(
            f"  {label:>5}  P(D)={res.p_win['D']:.3f}  median {res.margin_median * 100:+6.2f}"
            f"  80% [{lo * 100:+6.2f},{hi * 100:+6.2f}]  95% [{lo95 * 100:+6.2f},{hi95 * 100:+6.2f}]"
        )


if __name__ == "__main__":
    main()
