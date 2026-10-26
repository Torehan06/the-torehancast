"""Results-only races: one contest's vote totals → the update the publisher writes.

No baseline, prior or model is involved. An adapter's `parse_all_contests` returns a
ContestTotals per race it found; this module turns it into a ResultsOnlyUpdate, and
publishes a race as waiting when the contest isn't in the feed yet or its polls
haven't closed (counts before then are test data).
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import ResultsContest
from .publish import ResultsOnlyUpdate


@dataclass(frozen=True)
class ContestTotals:
    """One contest as the feed reports it, keyed by side ("D", "R", "D2", "other", ...)."""

    candidates: dict[str, str]  # side → name shown on the page
    votes: dict[str, int]  # side → votes; same keys as candidates
    pct_reporting: float | None  # the feed's fraction of units reporting; None if it doesn't say
    as_of: str | None = None


def update(contest: ResultsContest, state: str, totals: ContestTotals | None, as_of: str) -> ResultsOnlyUpdate:
    """The update for one contest; `totals=None` means no votes to publish (waiting)."""
    if totals is None:
        return ResultsOnlyUpdate(state, contest.race_id, {}, {}, None, as_of,
                                 race_type=contest.race_type, district=contest.district, in_feed=False)
    return ResultsOnlyUpdate(state, contest.race_id, dict(totals.candidates), dict(totals.votes),
                             totals.pct_reporting, totals.as_of or as_of,
                             race_type=contest.race_type, district=contest.district)
