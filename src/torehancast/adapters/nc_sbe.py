"""North Carolina: State Board of Elections results files.

One tab-separated file per election, precinct level, published at

    https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/{YYYY_MM_DD}/results_pct_{YYYYMMDD}.zip

Each row is one choice in one contest in one precinct, with separate columns per
vote type. The early-vote column was called "One Stop" through 2020 and
"Early Voting" from 2024.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from pathlib import Path

from ..candidates import CandidateMap
from ..schema import Cell, Snapshot, canonical_vote_type

BASE = "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS"
VOTE_COLUMNS = ("Election Day", "One Stop", "Early Voting", "Absentee by Mail", "Provisional")


def results_url(election_date: str, base: str = BASE) -> str:
    """election_date like '2024-11-05'."""
    y, m, d = election_date.split("-")
    return f"{base}/{y}_{m}_{d}/results_pct_{y}{m}{d}.zip"


def read_zip(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".txt"))
        return zf.read(name).decode("utf-8", errors="replace")


def parse(text: str, contest_name: str, cmap: CandidateMap, race: str) -> Snapshot:
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    vote_columns = [c for c in VOTE_COLUMNS if c in (reader.fieldnames or [])]

    votes: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    precincts: dict[str, set[str]] = defaultdict(set)
    reporting_precincts: dict[str, set[str]] = defaultdict(set)

    for row in reader:
        if row["Contest Name"] != contest_name:
            continue
        county = row["County"].strip().upper()
        precinct = row["Precinct"]
        key = cmap.key_for(row["Choice"])
        precincts[county].add(precinct)
        for col in vote_columns:
            n = int(row[col] or 0)
            votes[(county, canonical_vote_type(col))][key] += n
        if int(row["Election Day"] or 0) > 0:
            reporting_precincts[county].add(precinct)

    cells = [Cell(unit, vt, dict(v)) for (unit, vt), v in sorted(votes.items())]
    # NC's file has no explicit precinct status; "has any Election Day votes" is the
    # best available proxy for a precinct having reported.
    reporting = {c: len(reporting_precincts[c]) / len(p) for c, p in precincts.items() if p}
    return Snapshot("NC", race, None, cells, reporting, warnings=cmap.warnings())


def load_archive(directory: Path, election_date: str) -> str:
    compact = election_date.replace("-", "")
    return (directory / f"results_pct_{compact}.txt").read_text(encoding="utf-8", errors="replace")


# Adapter protocol (see adapters/__init__.py).

def fetch_source(client, feed) -> str:
    return read_zip(client.get(feed.url))


def final_snapshot(spec: dict, archives: Path, cmap: CandidateMap, key: str) -> Snapshot:
    return parse(load_archive(archives, spec["date"]), spec["contest"], cmap, key)
