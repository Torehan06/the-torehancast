"""Exact ballot-name matching.

Names are matched exactly as printed in the feed — never fuzzily. Alaska's 2026
ballot has two Dan Sullivans ("Sullivan, Dan S." is the senator, "Sullivan,
Daniel J." is not), and a fuzzy matcher would quietly merge them.
"""

from __future__ import annotations

OTHER = "other"


class CandidateMap:
    def __init__(self, ballot_names: dict[str, str]):
        """`ballot_names` maps the exact feed string to a candidate key ("D", "R", ...)."""
        self._by_name = dict(ballot_names)
        self.unmatched: set[str] = set()

    def key_for(self, ballot_name: str) -> str:
        key = self._by_name.get(ballot_name)
        if key is None:
            self.unmatched.add(ballot_name)
            return OTHER
        return key

    def warnings(self) -> list[str]:
        return [f"unmatched ballot name pooled into 'other': {n!r}" for n in sorted(self.unmatched)]

    def missing(self, seen: set[str]) -> list[str]:
        """Configured names that never appeared — usually a typo in config or a renamed candidate."""
        return sorted(set(self._by_name) - seen)
