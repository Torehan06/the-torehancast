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

from .. import results_only
from ..candidates import CandidateMap
from ..schema import Cell, Snapshot, canonical_vote_type

BASE = "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS"
VOTE_COLUMNS = ("Election Day", "One Stop", "Early Voting", "Absentee by Mail", "Provisional")
# A statewide contest rebuilt on a district's lines may leave this share of a split
# county's votes unassigned before the rebuild refuses to run.
MAX_UNMATCHED_SHARE = 0.01


def results_url(election_date: str, base: str = BASE) -> str:
    """election_date like '2024-11-05'."""
    y, m, d = election_date.split("-")
    return f"{base}/{y}_{m}_{d}/results_pct_{y}{m}{d}.zip"


def read_zip(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".txt"))
        return zf.read(name).decode("utf-8", errors="replace")


def _line_share(lines: dict, county: str, precinct: str) -> float | None:
    """The share of a precinct's votes inside `lines`; None for a name `lines` doesn't know.

    `lines` is {whole: [counties], parts: {county: {in: {precinct: share}, out: [precincts]}}}.
    A whole county needs no precinct names, so renames and vote-center rows can't lose votes.
    """
    if county in lines.get("whole", ()):
        return 1.0
    part = lines.get("parts", {}).get(county)
    if part is None:
        return 0.0
    if precinct in part["in"]:
        return float(part["in"][precinct])
    return 0.0 if precinct in part["out"] else None


def check_lines(text: str, contest_name: str, lines: dict) -> dict[str, float]:
    """Each split county's unmatched vote share. Raises rather than lose votes.

    Unmatched means a row with votes whose precinct name `lines` doesn't know, such as
    a renamed precinct or a county-wide early-voting row. A precinct named `in` that
    the file lacks is an error at any size.
    """
    totals: dict[str, int] = defaultdict(int)
    unmatched: dict[str, int] = defaultdict(int)
    seen: dict[str, set[str]] = defaultdict(set)
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        county = row["County"].strip().upper()
        if row["Contest Name"] != contest_name or county not in lines.get("parts", {}):
            continue
        seen[county].add(row["Precinct"])
        n = int(row["Total Votes"] or 0)
        totals[county] += n
        if _line_share(lines, county, row["Precinct"]) is None:
            unmatched[county] += n
    shares = {}
    for county, part in lines.get("parts", {}).items():
        if missing := set(part["in"]) - seen[county]:
            raise ValueError(f"{contest_name}: {county} has no rows for {sorted(missing)}")
        shares[county] = unmatched[county] / totals[county] if totals[county] else 0.0
        if shares[county] > MAX_UNMATCHED_SHARE:
            raise ValueError(f"{contest_name}: {shares[county]:.1%} of {county}'s votes are unmatched")
    return shares


def parse(text: str, contest_name: str, cmap: CandidateMap, race: str, lines: dict | None = None) -> Snapshot:
    """`lines` rebuilds a statewide contest on a district's lines (see `_line_share`)."""
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    vote_columns = [c for c in VOTE_COLUMNS if c in (reader.fieldnames or [])]

    votes: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    precincts: dict[str, set[str]] = defaultdict(set)
    reporting_precincts: dict[str, set[str]] = defaultdict(set)

    for row in reader:
        if row["Contest Name"] != contest_name:
            continue
        county = row["County"].strip().upper()
        precinct = row["Precinct"]
        share = 1.0 if lines is None else _line_share(lines, county, precinct)
        if not share:
            continue
        key = cmap.key_for(row["Choice"])
        precincts[county].add(precinct)
        for col in vote_columns:
            n = int(row[col] or 0)
            votes[(county, canonical_vote_type(col))][key] += n * share
        if int(row["Election Day"] or 0) > 0:
            reporting_precincts[county].add(precinct)

    cells = [Cell(unit, vt, {k: round(n) for k, n in v.items()}) for (unit, vt), v in sorted(votes.items())]
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
    text = load_archive(archives, spec["date"])
    if lines := spec.get("lines"):
        check_lines(text, spec["contest"], lines)
    return parse(text, spec["contest"], cmap, key, lines)


def parse_all_contests(text: str, contests) -> dict[str, results_only.ContestTotals]:
    """Every results-only contest in one pass.

    The file has no precinct status (`parse` uses a proxy for the model), so the
    public reporting fraction is None rather than a guess.
    """
    wanted = {c.contest: c for c in contests if c.contest}
    choices: dict[str, list[results_only.Choice]] = defaultdict(list)
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        if row["Contest Name"] in wanted:
            choices[row["Contest Name"]].append(
                results_only.Choice(row["Choice"], row["Choice Party"], int(row["Total Votes"] or 0)))
    return {wanted[name].race_id: results_only.totals(found, wanted[name].sides, None)
            for name, found in choices.items()}
