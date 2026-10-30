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

from .. import results_only
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


def contest_filter(contest: str) -> tuple[str, int | None]:
    """'USS' → ('USS', None); 'USR:022' → ('USR', 22), a district contest by `Juris1num`.

    In a district contest each county row covers only the county's part of the
    district, so the units are county-parts.
    """
    code, _, district = contest.partition(":")
    return code, int(district) if district else None


def parse(text: str, race_code: str, cmap: CandidateMap, race: str) -> Snapshot:
    """`race_code` is a contest as `contest_filter` reads it.

    A contest missing from the file has no votes (the extract leaves out unopposed
    races, e.g. FL-20 in 2024), so it yields an empty snapshot, not an error.
    """
    code, district = contest_filter(race_code)
    votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    reporting: dict[str, float] = {}
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        if row["RaceCode"] != code:
            continue
        if district is not None and int(row["Juris1num"] or 0) != district:
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


# Adapter protocol (see adapters/__init__.py). Florida's contest is its race code ("USS"),
# plus ":<district>" for a district contest ("USR:022").

def fetch_source(client, feed) -> str:
    return client.post(feed.url, dict(feed.params)).decode("latin-1")


def final_snapshot(spec: dict, archives: Path, cmap: CandidateMap, key: str) -> Snapshot:
    return parse(load_archive(archives, spec["date"]), spec["race_code"], cmap, key)


def parse_all_contests(text: str, contests) -> dict[str, results_only.ContestTotals]:
    """Every results-only contest in one pass. Contests are read as `contest_filter` does.

    Each county row repeats its precinct counts for every candidate, so reporting is
    counted once per county (per county part, for a district contest).
    """
    wanted = {contest_filter(c.contest): c for c in contests if c.contest}
    codes = {code for code, _ in wanted}
    choices: dict[str, list[results_only.Choice]] = defaultdict(list)
    units: dict[str, dict[str, tuple[int, int]]] = defaultdict(dict)
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        code, juris = row["RaceCode"], row["Juris1num"].strip()
        if code not in codes:
            continue
        contest = wanted.get((code, int(juris) if juris else None)) or wanted.get((code, None))
        if contest is None:
            continue
        party = row["PartyCode"].strip()
        choices[contest.race_id].append(
            results_only.Choice(ballot_name(row), party, int(row["CanVotes"] or 0), write_in=party == "WRI"))
        units[contest.race_id][row["CountyName"].strip().upper()] = (
            int(row["PrecinctsReporting"] or 0), int(row["Precincts"] or 0))
    by_id = {c.race_id: c for c in wanted.values()}
    return {
        race_id: results_only.totals(found, by_id[race_id].sides, results_only.fraction(
            sum(r for r, _ in units[race_id].values()), sum(t for _, t in units[race_id].values())))
        for race_id, found in choices.items()
    }
