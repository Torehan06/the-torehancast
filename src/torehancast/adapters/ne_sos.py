"""Nebraska: Secretary of State results service, the JSON behind electionresults.nebraska.gov.

    https://neresultswebservice.azurewebsites.us/ResultsAjax.svc/GetMapData
        ?type=SW&category=CTY&raceID=13224&osn=102&county=0&party=0

One response is one race: a row per candidate per county, with `calcCandidate`,
`calcCandidateVotes`, `PartyCode`, `PrecinctsReporting` and `TotalPrecincts`. No vote
types, so cells are `all`, as in Minnesota. Names come with stray double and trailing
spaces ("Pete  Ricketts "), which are collapsed.

A feed lists its races in `params.races` as `key=type:raceID:osn`, comma-separated, for
example `SEN=SW:13224:102,H1=CG:13165:103`. One fetch gets them all, and a contest in
config is one of those keys. District races need their own keys because every
congressional race has the same RaceName.

The state's archive (`GetMapDataArchive`) has 2012 and 2018 but returned nothing usable
for 2024, so that year comes from MEDSL's county file.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from .. import results_only
from ..candidates import CandidateMap
from ..schema import ALL, Cell, Snapshot


def _name(raw: str) -> str:
    return " ".join(raw.split())


def unit_id(county_name: str) -> str:
    return " ".join(county_name.split()).upper()


def _races(feed) -> dict[str, tuple[str, str, str]]:
    """`SEN=SW:13224:102,...` → {"SEN": ("SW", "13224", "102"), ...}."""
    races = {}
    for entry in feed.params["races"].split(","):
        key, _, spec = entry.strip().partition("=")
        race_type, race_id, osn = spec.split(":")
        races[key] = (race_type, race_id, osn)
    return races


def fetch_source(client, feed) -> dict[str, list[dict]]:
    """Every race the feed lists: {key: rows}."""
    document = {}
    for key, (race_type, race_id, osn) in _races(feed).items():
        url = f"{feed.url}?type={race_type}&category=CTY&raceID={race_id}&osn={osn}&county=0&party=0"
        document[key] = json.loads(client.get(url))["d"]
    return document


def _snapshot(rows: list[dict], cmap: CandidateMap, race: str) -> Snapshot:
    votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    reporting: dict[str, float] = {}
    for row in rows:
        county = unit_id(row["CountyName"])
        votes[county][cmap.key_for(_name(row["calcCandidate"]))] += int(row["calcCandidateVotes"] or 0)
        if row["TotalPrecincts"]:
            reporting[county] = row["PrecinctsReporting"] / row["TotalPrecincts"]
    cells = [Cell(county, ALL, dict(v)) for county, v in sorted(votes.items()) if sum(v.values())]
    reporting = {county: f for county, f in reporting.items() if sum(votes[county].values())}
    return Snapshot("NE", race, None, cells, reporting, warnings=cmap.warnings())


def parse(document: dict[str, list[dict]], contest: str, cmap: CandidateMap, race: str) -> Snapshot:
    return _snapshot(document.get(contest) or [], cmap, race)


def parse_all_contests(document: dict[str, list[dict]], contests) -> dict[str, results_only.ContestTotals]:
    found = {}
    for contest in contests:
        rows = document.get(contest.contest) or []
        if not rows:
            continue  # not in the feed yet: the race waits
        units = {row["CountyID"]: (row["PrecinctsReporting"], row["TotalPrecincts"]) for row in rows}
        choices = [results_only.Choice(_name(row["calcCandidate"]), row["PartyCode"], int(row["calcCandidateVotes"] or 0))
                   for row in rows]
        found[contest.race_id] = results_only.totals(choices, contest.sides, results_only.fraction(
            sum(r for r, _ in units.values()), sum(t for _, t in units.values())))
    return found


def _medsl_county(path: Path) -> list[dict]:
    """MEDSL's national county file, as rows shaped like the state's own."""
    with open(path, newline="", encoding="utf-8") as f:
        return [{"CountyName": row["county_name"], "calcCandidate": row["candidate"],
                 "calcCandidateVotes": row["votes"], "PrecinctsReporting": 0, "TotalPrecincts": 0}
                for row in csv.DictReader(f)
                if row["state_po"] == "NE" and row["office"] == "US Senate" and row["special"] == "FALSE"]


def final_snapshot(spec: dict, archives: Path, cmap: CandidateMap, key: str) -> Snapshot:
    if spec["format"] == "state":
        rows = json.loads((archives / spec["file"]).read_text())
    else:
        rows = _medsl_county(archives.parent / spec["file"])
    return _snapshot(rows, cmap, key)
