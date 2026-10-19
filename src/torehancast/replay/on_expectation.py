"""The "on-expectation" night: every batch arrives exactly as the model projected.

If results keep landing exactly where the model expected, the model has nothing to
be surprised by, so its confidence in the projected leader should only grow. A dip
means the model is reacting to something other than evidence (a discontinuity in
how partly counted counties are weighted, a prior leaking back in...).

Three modes, one per way states report vote types:
  split  per-type cells with completion flags (Georgia)
  delta  county totals + precincts reporting, split by BatchTracker (Florida)
  all    county totals + precincts reporting, no split (down-weighted `all` cells)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..adapters.fl_dos import BatchTracker
from ..model.simulate import RaceModel
from ..schema import ALL, EARLY, ELECTION_DAY, MAIL, PROVISIONAL, Cell, Snapshot

CHUNKS = 4  # Election Day (or `all`) arrives in this many equal pieces per county


@dataclass
class Step:
    share_counted: float
    p_leader: float
    median: float


def _plan(units: list[str], types: list[str], mode: str, rng: np.random.Generator) -> list[tuple[str, str, int]]:
    """(unit, vote type, chunk index) in arrival order: batch types first everywhere."""
    if mode == "all":
        per_county = [(ALL, k) for k in range(CHUNKS)]
    elif mode == "delta":
        per_county = [(EARLY, 0)] + [(ELECTION_DAY, k) for k in range(CHUNKS)]
    else:
        per_county = [(t, 0) for t in (EARLY, MAIL) if t in types]
        per_county += [(ELECTION_DAY, k) for k in range(CHUNKS)] + [(PROVISIONAL, 0)] * (PROVISIONAL in types)
    order = list(rng.permutation(units))
    return [(u, vt, k) for vt, k in per_county for u in order]


def run(model: RaceModel, mode: str, steps: int = 16, n_draws: int = 20_000, seed: int = 0) -> list[Step]:
    rng = np.random.default_rng(seed)
    empty = Snapshot("XX", "on-expectation", None, [])
    model.run(empty, n_draws, seed)
    proj = model.last_projection
    units, types = proj["units"], proj["types"]
    plan = _plan(units, types, mode, rng)
    blocks = [list(b) for b in np.array_split(np.arange(len(plan)), steps)]

    votes: dict[tuple[str, str], list[float]] = {}  # (unit, type) -> [two-party votes, D−R]
    complete: dict[tuple[str, str], float] = {}
    precincts: dict[str, float] = {}
    tracker = BatchTracker() if mode == "delta" else None
    out: list[Step] = []
    leader = None

    def snapshot() -> Snapshot:
        cells = [Cell(u, vt, {"D": int(round((n + d) / 2)), "R": int(round((n - d) / 2))}) for (u, vt), (n, d) in votes.items()]
        if mode == "delta":  # what Florida's feed actually shows: county totals only
            totals: dict[str, dict[str, int]] = {}
            for c in cells:
                t = totals.setdefault(c.unit_id, {"D": 0, "R": 0})
                t["D"] += c.votes["D"]
                t["R"] += c.votes["R"]
            flat = Snapshot("XX", "on-expectation", None, [Cell(u, ALL, v) for u, v in totals.items()], dict(precincts))
            return tracker.split(flat)
        return Snapshot("XX", "on-expectation", None, cells, dict(precincts), dict(complete))

    result = model.run(empty, n_draws, seed)
    for block in [[]] + list(blocks):
        proj = model.last_projection
        index = {(u, t): (i, j) for i, u in enumerate(proj["units"]) for j, t in enumerate(proj["types"])}
        for b in block:
            u, vt, k = plan[b]
            i, j = index[(u, vt if mode != "all" else ALL)]
            have_n, have_d = votes.get((u, vt), [0.0, 0.0])
            rem_n = max(proj["votes"][i, j] - have_n, 0.0)
            rem_d = proj["diff"][i, j] - have_d
            chunks_left = (CHUNKS - k) if vt in (ELECTION_DAY, ALL) else 1
            frac = 1.0 / chunks_left
            votes[(u, vt)] = [have_n + rem_n * frac, have_d + rem_d * frac]
            if vt in (ELECTION_DAY, ALL):
                precincts[u] = (k + 1) / CHUNKS
            if chunks_left == 1:
                complete[(u, vt)] = 1.0
        if block:
            result = model.run(snapshot(), n_draws, seed)
        if leader is None:
            leader = "D" if result.margin_median > 0 else "R"
        out.append(Step(result.share_counted, result.p_win[leader], result.margin_median))
    return out
