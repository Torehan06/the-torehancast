"""Run a replay: synthetic election night → model → checkpoints.

    python -m torehancast.replay.harness --state GA --order random --seed 1
    python -m torehancast.replay.harness --race 2026-IA-H01

A replay is keyed by a state (its Senate-style entry in config/replay.yaml) or by a
House race ID. A House race's replay spec lives under `replay:` in its state's
config/house/<ST>.yaml, next to the `elections:` it uses, so per-state sessions never
edit a shared file:

    replay:
      2026-IA-H01:
        primary: {baseline: ..., target: ..., tau_pair: [..., ...], prior: {...}}

Optional `units: <election>` in a pair restricts its baseline and replayed result to
that election's units: a district replayed on a statewide pair (2020 → 2024
president on the counties of 2024_house_01).

It inherits the state's traits from replay.yaml (batch vote types, arrival profile,
composition floor, synthetic split) and may override any of them. A Senate race ID
(2026-GA-SEN) means its state's entry. Units follow the race's `unit` in races.yaml:
`county-part` races key every unit `COUNTY|NN` (see units.py).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from functools import lru_cache

import pandas as pd
import yaml

from .. import demographics, districts, elections
from ..model import tau
from ..model.simulate import RaceModel, RacePrior, Result
from ..adapters.fl_dos import BatchTracker
from ..schema import Snapshot
from . import arrivals, units

CHECKPOINTS = (0.10, 0.25, 0.50, 0.75, 0.90)
PAIRS = ("primary", "secondary")


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
    key: str = ""  # what was replayed: the state, or a House race ID


def resolve(key: str) -> str:
    """A replay key: a state code or House race ID as given; a Senate race ID → its state."""
    identity = districts.race_identity(key)
    return identity[0] if identity and identity[1] != "house" else key


def state_of(key: str) -> str:
    identity = districts.race_identity(key)
    return identity[0] if identity else key


def _state_configs() -> dict:
    return yaml.safe_load((elections.CONFIG / "replay.yaml").read_text())


def house_replays(state: str) -> dict[str, dict]:
    """A state's House replay specs, from `replay:` in config/house/<ST>.yaml."""
    path = elections.CONFIG / "house" / f"{state}.yaml"
    return (yaml.safe_load(path.read_text()).get("replay") or {}) if path.exists() else {}


def replay_keys() -> list[str]:
    """Every replay: states from replay.yaml, then House race IDs from config/house/."""
    house = sorted(k for p in sorted((elections.CONFIG / "house").glob("*.yaml")) for k in house_replays(p.stem))
    return list(_state_configs()) + house


def replay_config(key: str) -> dict:
    key = resolve(key)
    states = _state_configs()
    if districts.race_identity(key) is None:
        return states[key]
    state = state_of(key)
    traits = {k: v for k, v in (states.get(state) or {}).items() if k not in PAIRS}
    return traits | house_replays(state).get(key, {})


def unit_scheme(key: str, unit: str | None = None) -> tuple[str, int | None]:
    """(unit kind, district). `unit` defaults to the race's row in races.yaml."""
    identity = districts.race_identity(resolve(key))
    if identity is None or identity[1] != "house":
        return units.COUNTY, None
    if unit is None:
        unit = yaml.safe_load((elections.CONFIG / "races.yaml").read_text())["races"][key]["unit"]
    return unit, identity[2]


def to_race_units(key: str, snap: Snapshot, unit: str | None = None) -> Snapshot:
    """An adapter's snapshot, in the race's own units (county parts for `county-part`)."""
    kind, district = unit_scheme(key, unit)
    return units.relabel(snap, district) if kind == units.COUNTY_PART else snap


def race_baseline(key: str, name: str, unit: str | None = None) -> pd.DataFrame:
    frame = elections.read_baseline(state_of(key), name)
    kind, district = unit_scheme(key, unit)
    return units.relabel_frame(frame, district) if kind == units.COUNTY_PART else frame


def restrict(snap: Snapshot, keep: set[str] | None) -> Snapshot:
    """Only the units in `keep` (all of them when None)."""
    if keep is None:
        return snap
    return Snapshot(
        snap.state, snap.race, snap.as_of,
        [c for c in snap.cells if c.unit_id in keep],
        {u: v for u, v in snap.unit_reporting.items() if u in keep},
        {k: v for k, v in snap.cell_complete.items() if k[0] in keep},
        list(snap.warnings),
    )


def replay_units(key: str, spec: dict) -> set[str] | None:
    """The units a replay pair is restricted to by `units:`, in the race's units."""
    return set(race_baseline(key, spec["units"]).unit_id) if spec.get("units") else None


@lru_cache(maxsize=None)
def _params(state: str, a: str, b: str):
    return tau.estimate(elections.read_baseline(state, a), elections.read_baseline(state, b))


@lru_cache(maxsize=None)
def final_result(key: str, election: str):
    """The certified result of `election`, in the race's units."""
    snap = elections.final_snapshot(elections.load(state_of(key), election))
    return to_race_units(key, snap)


def arrival_profile(cfg: dict, overrides: dict | None = None) -> arrivals.Profile:
    spec = dict(cfg.get("arrival_profile", {}))
    for key in ("batch_types", "chunked_types", "late_types"):
        if key in spec:
            spec[key] = tuple(spec[key])
    spec.update(overrides or {})
    return arrivals.Profile(**spec)


def make_model(key: str, baseline: str, tau_pair: tuple[str, str], prior: RacePrior,
               synthetic_split: dict | None = None, unit: str | None = None,
               only: set[str] | None = None) -> RaceModel:
    """The one place a RaceModel is assembled, for replays and for the live poller.

    `key` is a state or a race ID. Traits (batch vote types, composition floor) come
    from the replay config, so a floor tuned on replays is applied live too. A House
    race is built from its own baseline, in its own units, with demographics joined
    on exactly those units.
    """
    cfg = replay_config(key)
    state = state_of(key)
    params = _params(state, *tau_pair)
    if floor := cfg.get("composition_floor"):
        comp = params.composition
        params = replace(params, composition=replace(comp, **{k: max(getattr(comp, k), v) for k, v in floor.items()}))
    base = race_baseline(key, baseline, unit)
    if only is not None:
        if missing := only - set(base.unit_id):
            raise ValueError(f"{key}: {baseline} lacks units {sorted(missing)}")
        base = base[base.unit_id.isin(only)].reset_index(drop=True)
    demo = demographics.load(state)
    if unit_scheme(key, unit)[0] == units.COUNTY_PART:
        demo = units.demographics_for(demo, base.unit_id)
    return RaceModel(
        base,
        prior,
        params,
        batch_vote_types=tuple(cfg.get("batch_vote_types", ())),
        demographics=demo,
        synthetic_split=synthetic_split,
    )


def live_synthetic_split(key: str) -> dict | None:
    """The live baseline is the replay target year, so its pre-Election-Day share applies."""
    cfg = replay_config(key)
    if split := cfg.get("synthetic_split"):
        return {**split, **cfg.get("synthetic_target", {})}
    return None


def build_model(key: str, pair: str = "primary", prior_shift: float = 0.0) -> tuple[RaceModel, dict]:
    cfg = replay_config(key)
    spec = cfg[pair]
    prior = RacePrior(**spec["prior"])
    if prior_shift:
        prior = RacePrior(prior.margin + prior_shift, prior.margin_sd, prior.turnout_ratio, prior.turnout_sd)
    model = make_model(key, spec["baseline"], tuple(spec["tau_pair"]), prior, cfg.get("synthetic_split"),
                       only=replay_units(key, spec))
    return model, spec


def run(
    key: str,
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
    model, spec = build_model(key, pair, prior_shift)
    final = restrict(final_result(key, spec["target"]), replay_units(key, spec))
    totals = final.totals()
    two_party = totals["D"] + totals["R"]
    truth = (totals["D"] - totals["R"]) / two_party

    cfg = replay_config(key)
    profile = arrival_profile(cfg, profile_overrides)
    delta = cfg.get("vote_split") == "delta"
    if delta:  # Florida: archive has no vote types; invent them, then hide them again
        final = arrivals.synthesize_modes(final, seed, **cfg.get("synthetic_target", {}))
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
    return Replay(state_of(key), pair, truth, start, checkpoints, end, key)


def main() -> None:
    ap = argparse.ArgumentParser()
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--state")
    which.add_argument("--race", help="a race ID, e.g. 2026-IA-H01")
    ap.add_argument("--pair", default="primary")
    ap.add_argument("--order", default="random", choices=arrivals.ORDERS)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--prior-shift", type=float, default=0.0)
    args = ap.parse_args()
    r = run(args.race or args.state, args.pair, args.order, args.seed, prior_shift=args.prior_shift)
    print(f"{r.key} {r.pair} order={args.order} seed={args.seed} truth {r.truth_margin * 100:+.2f}")
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
