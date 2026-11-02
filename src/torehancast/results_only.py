"""Results-only races: one contest's vote totals → the update the publisher writes.

No baseline, prior or model is involved. An adapter's `parse_all_contests` returns a
ContestTotals per race it found; this module turns it into a ResultsOnlyUpdate, and
publishes a race as waiting when the contest isn't in the feed yet or its polls
haven't closed (counts before then are test data).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .config import ResultsContest
from .publish import ResultsOnlyUpdate

OTHER = "other"
OTHER_NAME = "Other candidates"
MAX_NAMED = 5  # the config loader's limit for `sides`, applied to automatic keys too

# A feed's party label (first three letters, upper-cased) → side letter. Unknown labels,
# write-ins and unlabelled candidates pool into "other"; a contest's `sides` in config
# names anyone who should stand on their own. Ambiguous labels stay out: SC's "UNC" is
# the United Citizens Party, not "unaffiliated", and its write-in line is labelled "NON".
PARTY_SIDES = {
    "DEM": "D", "DFL": "D", "D": "D",
    "REP": "R", "R": "R",
    "LIB": "L", "LPF": "L",
    "GRE": "G", "GRN": "G",
    "CON": "C", "CST": "C",
    "IND": "I", "NPA": "I", "UNA": "I",
}


@dataclass(frozen=True)
class ContestTotals:
    """One contest as the feed reports it, keyed by side ("D", "R", "D2", "other", ...)."""

    candidates: dict[str, str]  # side → name shown on the page
    votes: dict[str, int]  # side → votes; same keys as candidates
    pct_reporting: float | None  # the feed's fraction of units reporting; None if it doesn't say
    as_of: str | None = None


@dataclass(frozen=True)
class Choice:
    """One ballot line as an adapter reads it, before side keys are assigned."""

    name: str  # exactly as the feed prints it; also the name shown on the page
    party: str | None
    votes: int
    write_in: bool = False


def _write_in(name: str) -> bool:
    return name.strip().lower().replace("-", "").replace(" ", "").startswith(("writein", "scattering"))


def party_side(label: str | None) -> str | None:
    return PARTY_SIDES.get(label.strip().upper()[:3]) if label else None


def totals(choices: Iterable[Choice], sides: dict[str, str], pct_reporting: float | None,
           as_of: str | None = None) -> ContestTotals:
    """Side-keyed totals for one contest, summing repeated names (one row per county).

    Keys come from feed order, never from vote order, so a candidate keeps the same
    key all night: config `sides` first, then D and R, then other parties (D2, D3 for a
    second and third candidate of one party). Past five named candidates, the rest pool
    into "other" with write-ins and unlabelled candidates.
    """
    votes: dict[str, int] = {}
    party: dict[str, str | None] = {}
    write_in: set[str] = set()
    for c in choices:
        if type(c.votes) is not int or c.votes < 0:
            raise ValueError(f"{c.name!r}: votes must be a nonnegative integer")
        votes[c.name] = votes.get(c.name, 0) + c.votes
        party.setdefault(c.name, c.party)
        if c.write_in or _write_in(c.name):
            write_in.add(c.name)

    key: dict[str, str] = {n: s for n, s in sides.items() if n in votes}
    taken = {s for s in key.values() if s != OTHER}
    auto = [n for n in votes if n not in key and n not in write_in and party_side(party[n])]
    auto.sort(key=lambda n: {"D": 0, "R": 1}.get(party_side(party[n]), 2))  # stable: feed order otherwise
    for name in auto:
        letter = party_side(party[name])
        if len(taken) >= MAX_NAMED:
            break
        side = next((s for s in [letter] + [f"{letter}{i}" for i in range(2, 10)] if s not in taken), None)
        if side is None:
            continue
        key[name] = side
        taken.add(side)

    # Named candidates in key order (config, then D, R, other parties), "other" last.
    out_names = {side: name for name, side in key.items() if side != OTHER}
    out_votes = {side: votes[name] for name, side in key.items() if side != OTHER}
    pooled = [n for n in votes if key.get(n, OTHER) == OTHER]
    if pooled:
        out_names[OTHER] = OTHER_NAME
        out_votes[OTHER] = sum(votes[n] for n in pooled)
    return ContestTotals(out_names, out_votes, pct_reporting, as_of)


def fraction(reported: int, total: int) -> float | None:
    """Units reporting as the feed counts them; None when the feed gives no total."""
    return min(reported / total, 1.0) if total > 0 else None


def update(contest: ResultsContest, state: str, totals: ContestTotals | None, as_of: str) -> ResultsOnlyUpdate:
    """The update for one contest; `totals=None` means no votes to publish (waiting)."""
    if totals is None:
        return ResultsOnlyUpdate(state, contest.race_id, {}, {}, None, as_of,
                                 race_type=contest.race_type, district=contest.district, in_feed=False)
    return ResultsOnlyUpdate(state, contest.race_id, dict(totals.candidates), dict(totals.votes),
                             totals.pct_reporting, totals.as_of or as_of,
                             race_type=contest.race_type, district=contest.district)
