"""Florida: Department of State results extract.

The Division of Elections serves a tab-separated, county-level extract of every
race from a form POST:

    POST https://results.elections.myflorida.com/ResultsExtract.Asp
         ElectionDate=11/5/2024&OfficialResults=Y|N&PartyRaces=N&DataMode=

Each row is one candidate in one county, with `Precincts` / `PrecinctsReporting`.
There is no vote-type split, but Florida law has counties post early and mail
ballots before any precinct reports, so `BatchTracker` recovers the split from
successive snapshots.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from pathlib import Path

from ..candidates import CandidateMap
from ..schema import ALL, EARLY, ELECTION_DAY, Cell, Snapshot

URL = "https://results.elections.myflorida.com/ResultsExtract.Asp"


def form(election_date: str, official: bool) -> dict:
    """election_date like '2024-11-05'."""
    y, m, d = election_date.split("-")
    return {
        "ElectionDate": f"{int(m)}/{int(d)}/{y}",
        "OfficialResults": "Y" if official else "N",
        "PartyRaces": "N",
        "DataMode": "",
        "FormsButton2": "Download",
    }


def ballot_name(row: dict) -> str:
    """'Scott, Rick' — the exact string candidates are matched on."""
    return f"{row['CanNameLast'].strip()}, {row['CanNameFirst'].strip()}"


def parse(text: str, race_code: str, cmap: CandidateMap, race: str) -> Snapshot:
    votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    reporting: dict[str, float] = {}
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        if row["RaceCode"] != race_code:
            continue
        county = row["CountyName"].strip().upper()
        votes[county][cmap.key_for(ballot_name(row))] += int(row["CanVotes"] or 0)
        total = int(row["Precincts"] or 0)
        if total:
            reporting[county] = int(row["PrecinctsReporting"] or 0) / total
    cells = [Cell(county, ALL, dict(v)) for county, v in sorted(votes.items())]
    return Snapshot("FL", race, None, cells, reporting, warnings=cmap.warnings())


def load_archive(directory: Path, election_date: str) -> str:
    return (directory / f"extract_{election_date.replace('-', '')}.txt").read_text(encoding="latin-1")


class BatchTracker:
    """Splits Florida's county totals into pre-Election-Day and Election Day votes.

    Votes a county posts while none of its precincts have reported are its early +
    mail batch. Once precincts start reporting, that batch is frozen and marked
    complete, and everything added afterwards counts as Election Day. Keep one
    tracker per race for the whole night.
    """

    def __init__(self):
        self.early: dict[str, dict[str, int]] = {}
        self.frozen: set[str] = set()

    def split(self, snap: Snapshot) -> Snapshot:
        cells: list[Cell] = []
        complete: dict[tuple[str, str], float] = {}
        warnings = list(snap.warnings)
        for c in snap.cells:
            started = snap.unit_reporting.get(c.unit_id, 0.0) > 0
            if c.unit_id not in self.frozen:
                if not started:
                    self.early[c.unit_id] = dict(c.votes)  # still the pre-Election-Day batch
                else:
                    # Freeze the last total seen before precincts started reporting. If we
                    # never saw one, the split is unknowable: book it all as early.
                    if c.unit_id not in self.early:
                        self.early[c.unit_id] = dict(c.votes)
                        warnings.append(f"{c.unit_id}: first seen with precincts reporting; early/ED split unknown")
                    self.frozen.add(c.unit_id)
            if not c.total:
                continue
            early = self.early.get(c.unit_id, {})
            complete[(c.unit_id, EARLY)] = 1.0  # Florida posts the pre-ED batch in one go
            cells.append(Cell(c.unit_id, EARLY, dict(early)))
            if c.unit_id in self.frozen:
                ed = {k: max(v - early.get(k, 0), 0) for k, v in c.votes.items()}
                cells.append(Cell(c.unit_id, ELECTION_DAY, ed))
        return Snapshot(snap.state, snap.race, snap.as_of, cells, dict(snap.unit_reporting), complete, warnings)
