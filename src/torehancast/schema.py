"""The common shape every adapter produces.

Each state publishes results differently, but by the time data reaches the model
it is a list of `Cell`s: votes for one geographic unit and one vote type.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Canonical vote types. "all" is used when a state doesn't split its counts.
EARLY = "early"
MAIL = "mail"
ELECTION_DAY = "election_day"
PROVISIONAL = "provisional"
ALL = "all"
VOTE_TYPES = (EARLY, MAIL, ELECTION_DAY, PROVISIONAL, ALL)

# Raw labels seen in official feeds -> canonical vote type. Matching is on the
# lower-cased, whitespace-collapsed label. Unknown labels raise rather than guess.
_VOTE_TYPE_LABELS = {
    # Georgia (Enhanced Voting); labels change almost every cycle.
    "advance in person": EARLY,
    "advanced voting": EARLY,
    "advance voting votes": EARLY,
    "advanced voting votes": EARLY,
    "absentee by mail": MAIL,
    "absentee by mail votes": MAIL,
    "election day": ELECTION_DAY,
    "election day votes": ELECTION_DAY,
    "provisional": PROVISIONAL,
    "provisional votes": PROVISIONAL,
    # North Carolina
    "early voting": EARLY,
    "one stop": EARLY,
    # South Carolina (Clarity) — "Provionsal" is a real typo in the 2024 feed;
    # 2020 called early voting "In-Person Absentee".
    "in-person absentee": EARLY,
    "provionsal": PROVISIONAL,
    "failsafe": PROVISIONAL,
    "failsafe provisional": PROVISIONAL,
    # Iowa (Clarity) — early in-person and mail absentee are combined under "Absentee".
    "absentee": EARLY,
}


class UnknownVoteType(ValueError):
    """A feed used a vote-type label we have never seen. Stop and look, don't guess."""


def canonical_vote_type(label: str) -> str:
    key = " ".join(label.lower().split())
    if key in VOTE_TYPES:
        return key
    try:
        return _VOTE_TYPE_LABELS[key]
    except KeyError:
        raise UnknownVoteType(f"unrecognised vote-type label {label!r}") from None


@dataclass(frozen=True)
class Cell:
    """Votes for one unit (county / House District) and one vote type.

    `votes` maps a candidate key from config (e.g. "D", "R", or "sullivan_dan_s")
    to a vote count. Votes for unconfigured candidates are pooled under "other".
    """

    unit_id: str
    vote_type: str
    votes: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.votes.values())


@dataclass
class Snapshot:
    """Everything one fetch of one race's feed tells us."""

    state: str
    race: str
    as_of: str | None
    cells: list[Cell]
    # unit_id -> fraction of the unit's precincts reporting (0..1), when the feed says.
    unit_reporting: dict[str, float] = field(default_factory=dict)
    # (unit_id, vote_type) -> 1.0 fully reported / 0.0 nothing yet, when the feed says
    # per vote type (Georgia does). Partly reported cells are simply left out.
    cell_complete: dict[tuple[str, str], float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def units(self) -> set[str]:
        return {c.unit_id for c in self.cells}

    def totals(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.cells:
            for k, v in c.votes.items():
                out[k] = out.get(k, 0) + v
        return out
