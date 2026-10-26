"""Synthetic election nights built from certified final results.

Archives only hold final totals, not the order votes arrived in. So we invent
plausible nights from a per-state profile, plus deliberately hostile ones:

Realistic orders (must meet the coverage thresholds):
  random       counties report at random times (bigger ones slower); early + mail
               first, then Election Day in precinct-sized chunks, provisional last
  timezone     random, but units whose polls close later start later (Florida's
               Central-time Panhandle closes an hour after the rest of the state)

Adversarial orders (must only avoid confident wrong calls):
  d_first      the most Democratic counties report first
  r_first      the most Republican counties report first
  ed_first     Election Day votes come in before early and mail everywhere

A state's profile can add its own rules: `batch_before_precincts` (Florida law: the
whole pre-Election-Day batch is posted before any precinct) and `late_mail` (some
counties post a slice of mail ballots after precincts have started).

Election Day chunks are not miniature copies of the county: their D and R votes are
split separately, so a partial count leans one way or the other like real precincts.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..schema import EARLY, ELECTION_DAY, MAIL, PROVISIONAL, Cell, Snapshot
from .units import county_of

REALISTIC_ORDERS = ("random", "timezone")
ADVERSARIAL_ORDERS = ("d_first", "r_first", "ed_first")
ORDERS = REALISTIC_ORDERS + ADVERSARIAL_ORDERS


@dataclass(frozen=True)
class Event:
    time: float  # hours after polls close
    unit_id: str
    vote_type: str
    votes: dict[str, int]  # increment
    completes_cell: bool
    precinct_fraction: float | None  # unit's ED precincts reporting after this event


@dataclass(frozen=True)
class Profile:
    batch_types: tuple[str, ...] = (EARLY, MAIL)  # arrive in one go per county
    chunked_types: tuple[str, ...] = (ELECTION_DAY,)
    late_types: tuple[str, ...] = (PROVISIONAL,)
    chunks: int = 8  # Election Day chunks per county
    heterogeneity: float = 25.0  # Dirichlet concentration: lower = lumpier chunks
    big_county_batches: int = 3  # the largest counties release early votes in pieces
    big_counties: int = 5
    batch_before_precincts: bool = False  # every batch piece lands before the first precinct
    # {probability, share: [lo, hi]}: chance a county posts a late slice of its mail /
    # early batch after precincts start, and how big that slice is.
    late_mail: dict | None = None
    # {hours, units: [...]}: units whose polls close later (used by the timezone order).
    late_close: dict | None = None


def _split(total: int, k: int, rng: np.random.Generator, concentration: float) -> np.ndarray:
    if total == 0:
        return np.zeros(k, dtype=int)
    shares = rng.dirichlet(np.full(k, concentration))
    counts = np.floor(shares * total).astype(int)
    counts[rng.integers(k)] += total - counts.sum()
    return counts


def timeline(final: Snapshot, order: str, seed: int, profile: Profile = Profile()) -> list[Event]:
    rng = np.random.default_rng(seed)
    by_unit: dict[str, dict[str, dict[str, int]]] = {}
    for c in final.cells:
        by_unit.setdefault(c.unit_id, {})[c.vote_type] = c.votes
    units = sorted(by_unit)
    size = np.array([sum(sum(v.values()) for v in by_unit[u].values()) for u in units], dtype=float)
    lean = np.array(
        [sum(v.get("D", 0) - v.get("R", 0) for v in by_unit[u].values()) / max(s, 1) for u, s in zip(units, size)]
    )
    big = set(np.array(units)[np.argsort(-size)[: profile.big_counties]])

    # When each county starts reporting (hours after close). Bigger counties are slower.
    rank = np.argsort(np.argsort(size)) / max(len(units) - 1, 1)
    start = rng.uniform(0, 1.0, len(units)) * (0.5 + rank)
    if order == "timezone" and profile.late_close:
        late = set(profile.late_close["units"])  # county names; a county part closes with its county
        start = start + np.array([profile.late_close["hours"] if county_of(u) in late else 0.0 for u in units])
    elif order == "d_first":
        start = np.sort(start)[np.argsort(np.argsort(-lean))]
    elif order == "r_first":
        start = np.sort(start)[np.argsort(np.argsort(lean))]

    events: list[Event] = []
    for u, t0 in zip(units, start):
        cells = by_unit[u]
        pieces = profile.big_county_batches if u in big else 1
        ed_start = t0 + 0.25 if order != "ed_first" else t0
        if profile.batch_before_precincts and order != "ed_first":
            ed_start = t0 + 0.4 * (pieces - 1) + 0.25
        ed_span = 1.5 + 3.0 * rng.random()
        batch_time = t0 if order != "ed_first" else ed_start + ed_span + 0.25
        late_mail = profile.late_mail and rng.random() < profile.late_mail["probability"]

        for vt in profile.batch_types:
            if vt not in cells:
                continue
            votes = dict(cells[vt])
            if late_mail:  # carve off a slice that arrives mid-Election-Day
                lo, hi = profile.late_mail["share"]
                slice_ = {k: int(round(n * rng.uniform(lo, hi))) for k, n in votes.items()}
                votes = {k: n - slice_[k] for k, n in votes.items()}
                events.append(Event(ed_start + 0.5 * ed_span, u, vt, slice_, True, None))  # last piece
            parts = {k: _split(n, pieces, rng, 50.0) for k, n in votes.items()}
            for j in range(pieces):
                events.append(
                    Event(batch_time + 0.4 * j, u, vt, {k: int(p[j]) for k, p in parts.items()}, j == pieces - 1 and not late_mail, None)
                )

        for vt in profile.chunked_types:
            if vt not in cells:
                continue
            k = profile.chunks
            parts = {cand: _split(n, k, rng, profile.heterogeneity) for cand, n in cells[vt].items()}
            times = np.sort(ed_start + ed_span * rng.random(k))
            for j in range(k):
                events.append(
                    Event(float(times[j]), u, vt, {c: int(p[j]) for c, p in parts.items()}, j == k - 1, (j + 1) / k)
                )

        for vt in profile.late_types:
            if vt in cells:
                events.append(Event(ed_start + ed_span + 1.0, u, vt, dict(cells[vt]), True, None))

    return sorted(events, key=lambda e: e.time)


def snapshots(final: Snapshot, events: list[Event], step_hours: float = 0.25):
    """Yield (time, Snapshot) every `step_hours`, as a feed would show it."""
    totals: dict[tuple[str, str], dict[str, int]] = {}
    complete: dict[tuple[str, str], float] = {}
    precincts: dict[str, float] = {}
    i, t = 0, 0.0
    end = events[-1].time if events else 0.0
    while True:
        while i < len(events) and events[i].time <= t:
            e = events[i]
            cell = totals.setdefault((e.unit_id, e.vote_type), {})
            for k, n in e.votes.items():
                cell[k] = cell.get(k, 0) + n
            if e.completes_cell:
                complete[(e.unit_id, e.vote_type)] = 1.0
            if e.precinct_fraction is not None:
                precincts[e.unit_id] = e.precinct_fraction
            i += 1
        cells = [Cell(u, vt, dict(v)) for (u, vt), v in sorted(totals.items())]
        yield t, Snapshot(final.state, final.race, f"T+{t:.2f}h", cells, dict(precincts), dict(complete))
        if t > end:
            return
        t += step_hours


def synthesize_modes(final: Snapshot, seed: int, early_share: float = 0.72, gap: float = 0.10) -> Snapshot:
    """Split `all`-only final results into early and election_day cells.

    For states whose archives have no vote-type split (Florida). Each county gets a
    pre-Election-Day share around `early_share` and an Election Day that leans R by
    about `gap` relative to its early vote. This is invented, so a replay built on it
    tests the mechanics of the delta inference, not Florida's real 2024 mode split.
    """
    rng = np.random.default_rng(seed + 10_000)
    cells = []
    for c in final.cells:
        D, R = c.votes.get("D", 0), c.votes.get("R", 0)
        n = D + R
        if n == 0:
            continue
        s = float(np.clip(rng.normal(early_share, 0.06), 0.4, 0.9))
        g = rng.normal(gap, 0.05)
        m = (D - R) / n
        m_early = np.clip(m + g * (1 - s), -1, 1)
        early_n = int(round(n * s))
        early_d = int(round(early_n * m_early))
        eD, eR = (early_n + early_d) // 2, early_n - (early_n + early_d) // 2
        eD, eR = min(eD, D), min(eR, R)
        cells.append(Cell(c.unit_id, EARLY, {"D": eD, "R": eR}))
        cells.append(Cell(c.unit_id, ELECTION_DAY, {"D": D - eD, "R": R - eR}))
    return Snapshot(final.state, final.race, final.as_of, cells)


def flatten(snap: Snapshot) -> Snapshot:
    """What a county-totals feed (Florida) shows: one `all` cell per county + precincts."""
    totals: dict[str, dict[str, int]] = {}
    for c in snap.cells:
        t = totals.setdefault(c.unit_id, {})
        for k, n in c.votes.items():
            t[k] = t.get(k, 0) + n
    from ..schema import ALL

    cells = [Cell(u, ALL, v) for u, v in sorted(totals.items())]
    return Snapshot(snap.state, snap.race, snap.as_of, cells, dict(snap.unit_reporting))
