"""Ohio: Secretary of State election-night XML feed (`liveresults.ohiosos.gov`).

One NIST SP 1500-100 document per election, about 1.2 MB, refreshed every three
minutes on the night:

    https://liveresults.ohiosos.gov/Api/v1/download?filename=VSSC1622XmlFileBlob

Things about its shape that matter here:

* Each contest's `<VoteCounts>` lists one aggregate line (`State` or `Congressional`)
  plus one line per county. Only the county lines are summed.
* There are two `GpUnit`s called County for each county: "Adams" carries the precinct
  counts (`SubUnitsReported`, `TotalSubUnits`) and "Adams County" is a court district
  with none. A county is a unit that has `TotalSubUnits`.
* Precinct counts are for the whole county, so they measure a statewide contest's
  reporting but not a House district that splits a county. District contests publish
  no reporting fraction rather than a wrong one.
* Counts are `Total` only, with no vote-type split, so the live model uses `BatchTracker`
  as Florida does: votes posted before any precinct reports are the early + absentee
  batch.
* `IsTest="true"` marks test data. The poller's polls-close guard holds back anything
  published before polls close; the flag also becomes a snapshot warning.

Ohio's own results archive sits behind a bot challenge, so the historical elections
come from research copies of the official canvass (see `ARCHIVE_READERS`). Their
statewide totals were checked against the published results.
"""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .. import results_only
from ..candidates import CandidateMap
from ..schema import ALL, Cell, Snapshot

URL = "https://liveresults.ohiosos.gov/Api/v1/download?filename=VSSC1622XmlFileBlob"
NS = "{http://grouper.ieee.org/groups/1622/groups/2/V1/1622_2-election_results_reporting.xsd}"


def unit_id(county: str) -> str:
    return county.strip().upper()


@dataclass(frozen=True)
class _Ballot:
    name: str
    party: str | None
    write_in: bool
    votes: dict[str, int]  # county unit ID → votes


@dataclass(frozen=True)
class _Document:
    as_of: str | None
    is_test: bool
    reporting: dict[str, tuple[int, int]]  # county unit ID → (precincts reporting, total)
    contests: dict[str, tuple[bool, list[_Ballot]]]  # contest name → (statewide?, ballots)


def _read(xml_text: str) -> _Document:
    root = ET.fromstring(xml_text)
    units = {u.attrib["ObjectId"]: u for u in root.find(f"{NS}GpUnitCollection")}
    counties = {
        object_id: unit_id(u.attrib["Name"]) for object_id, u in units.items()
        if u.attrib.get("Type") == "County" and "TotalSubUnits" in u.attrib
    }
    reporting = {
        counties[object_id]: (int(units[object_id].attrib.get("SubUnitsReported") or 0),
                              int(units[object_id].attrib["TotalSubUnits"]))
        for object_id in counties
    }
    parties = {p.attrib["ObjectId"]: p.attrib.get("Abbreviation") for p in root.find(f"{NS}PartyCollection")}
    election = root.find(f"{NS}Election")
    people = {}
    for c in election.find(f"{NS}CandidateCollection"):
        people[c.attrib["ObjectId"]] = (c.findtext(f"{NS}BallotName/{NS}LanguageString", "").strip(),
                                        parties.get(c.findtext(f"{NS}PartyId")))
    contests = {}
    for contest in election.find(f"{NS}ContestCollection"):
        scope = units.get(contest.findtext(f"{NS}JurisdictionalScopeId"))
        ballots = []
        for selection in contest.findall(f"{NS}BallotSelection"):
            ids = (selection.findtext(f"{NS}CandidateId") or selection.findtext(f"{NS}CandidateIds") or "").split()
            if not ids:  # a ballot question, not a candidate
                continue
            name, party = people[ids[0]]
            votes = {
                counties[v.findtext(f"{NS}GpUnitId")]: int(v.attrib.get("Count") or 0)
                for v in selection.iter(f"{NS}VoteCounts")
                if v.attrib.get("Type") == "Total" and v.findtext(f"{NS}GpUnitId") in counties
            }
            ballots.append(_Ballot(name, party, selection.attrib.get("IsWriteIn") == "true", votes))
        statewide = scope is not None and scope.attrib.get("Type") == "State"
        contests[contest.attrib["Name"].strip()] = (statewide, ballots)
    return _Document(root.attrib.get("GeneratedDate"), root.attrib.get("IsTest") == "true", reporting, contests)


def parse(xml_text: str, contest_name: str, cmap: CandidateMap, race: str) -> Snapshot:
    """One modeled race: every county as an `all` cell, precinct reporting per county."""
    doc = _read(xml_text)
    warnings = ["feed is marked IsTest: test data"] if doc.is_test else []
    if contest_name not in doc.contests:
        return Snapshot("OH", race, doc.as_of, [], {}, warnings=warnings + cmap.warnings())
    votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    _, ballots = doc.contests[contest_name]
    for ballot in ballots:
        key = cmap.key_for(ballot.name)
        for county, n in ballot.votes.items():
            votes[county][key] += n
    cells = [Cell(county, ALL, dict(v)) for county, v in sorted(votes.items())]
    reporting = {county: r / t for county, (r, t) in doc.reporting.items() if t > 0 and county in votes}
    return Snapshot("OH", race, doc.as_of, cells, reporting, warnings=warnings + cmap.warnings())


# Adapter protocol (see adapters/__init__.py).

def fetch_source(client, feed) -> str:
    return client.get(feed.url).decode("utf-8-sig")


def parse_all_contests(xml_text: str, contests) -> dict[str, results_only.ContestTotals]:
    doc = _read(xml_text)
    out = {}
    for contest in contests:
        statewide, ballots = doc.contests.get(contest.contest, (False, None)) if contest.contest else (False, None)
        if ballots is None:
            continue
        pct = None
        if statewide:
            pct = results_only.fraction(sum(r for r, _ in doc.reporting.values()),
                                        sum(t for _, t in doc.reporting.values()))
        choices = [results_only.Choice(b.name, b.party, sum(b.votes.values()), b.write_in) for b in ballots]
        out[contest.race_id] = results_only.totals(choices, contest.sides, pct, doc.as_of)
    return out


def _medsl_county(path: Path) -> Iterator[tuple[str, str, int]]:
    """MEDSL `2024-senate-county.csv`: every state's Senate race, one row per candidate."""
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["state_po"] == "OH":
                yield row["county_name"], row["candidate"], int(row["votes"])


def _medsl_precinct(path: Path) -> Iterator[tuple[str, str, int]]:
    """MEDSL's 2018 Ohio precinct zip: one row per office, candidate and precinct."""
    with zipfile.ZipFile(path) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".csv"))
        with archive.open(name) as raw:
            for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline="")):
                if row["office"] == "US SENATE":
                    yield row["county_name"], row["candidate"], int(float(row["votes"] or 0))


def _openelections_county(path: Path) -> Iterator[tuple[str, str, int]]:
    """OpenElections' 2012 county file for one office."""
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            yield row["county"], row["candidate"], int(row["votes"] or 0)


ARCHIVE_READERS = {
    "medsl_county": _medsl_county,
    "medsl_precinct": _medsl_precinct,
    "openelections_county": _openelections_county,
}


def final_snapshot(spec: dict, archives: Path, cmap: CandidateMap, key: str) -> Snapshot:
    votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for county, candidate, n in ARCHIVE_READERS[spec["format"]](archives / spec["file"]):
        votes[unit_id(county)][cmap.key_for(candidate)] += n
    cells = [Cell(county, ALL, dict(v)) for county, v in sorted(votes.items())]
    return Snapshot("OH", key, None, cells, warnings=cmap.warnings())
