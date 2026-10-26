"""Georgia: the Secretary of State's Enhanced Voting results site.

Georgia left Clarity before 2024. The results page is an Angular app backed by a
JSON API:

    {base}/api/elections/{jurisdiction}/{election_code}/data

`jurisdiction` is "Georgia" for statewide totals or a county short name such as
"appling-county-ga". Only the county files carry county-level numbers, so a full
poll is 1 + 159 requests. Each ballot option has `groupResults`, the vote-type
split (Advance / Election Day / Mail / Provisional).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..candidates import CandidateMap
from ..http import PoliteClient
from ..schema import Cell, Snapshot, canonical_vote_type

BASE = "https://results.sos.ga.gov/results/public"


def data_url(jurisdiction: str, election_code: str, base: str = BASE) -> str:
    return f"{base}/api/elections/{jurisdiction}/{election_code}/data"


def counties(state_doc: dict) -> list[tuple[str, str]]:
    """(short_name, display name) for every county, from the statewide document."""
    out = []
    for loc in state_doc["jurisdiction"]["childLocalities"]:
        out.append((loc["shortName"], _text(loc["name"])))
    return out


def unit_id(display_name: str) -> str:
    """'Appling County' -> 'APPLING'. Stable across election years."""
    name = display_name.upper().strip()
    return name.removesuffix(" COUNTY").strip()


def _text(localized: list[dict]) -> str:
    return next(t["text"] for t in localized if t.get("languageId") == "en")


def find_contest(doc: dict, contest_name: str) -> dict | None:
    for item in doc.get("ballotItems") or []:
        if _text(item["name"]) == contest_name:
            return item
    return None


# Per-vote-type reporting status keys used by Enhanced Voting.
_STATUS = {
    "reporting-status-fully-reported": 1.0,
    "reporting-status-not-reported": 0.0,
}


def group_status(doc: dict) -> dict[str, float]:
    """vote type -> 1.0 / 0.0 for groups the county marks fully or not reported."""
    out = {}
    for g in doc["election"].get("groupReportingStatus") or []:
        status = _STATUS.get(g.get("reportingStatusClientTextKey"))
        if status is not None:
            out[canonical_vote_type(_text(g["groupName"]))] = status
    return out


def parse_county(doc: dict, contest_name: str, cmap: CandidateMap) -> tuple[list[Cell], float | None]:
    """Cells for one county document, plus its precinct-reporting fraction."""
    county_name = _text(doc["jurisdiction"]["name"])
    item = find_contest(doc, contest_name)
    if item is None:
        return [], None
    uid = unit_id(county_name)

    by_type: dict[str, dict[str, int]] = {}
    for option in item["summaryResults"]["ballotOptions"]:
        key = cmap.key_for(_text(option["name"]))
        for group in option.get("groupResults") or []:
            vt = canonical_vote_type(_text(group["groupName"]))
            votes = by_type.setdefault(vt, {})
            votes[key] = votes.get(key, 0) + int(group["voteCount"] or 0)

    status = item.get("reportingStatus") or {}
    total_units = status.get("totalUnits") or 0
    reporting = status["reportingUnits"] / total_units if total_units else None
    return [Cell(uid, vt, votes) for vt, votes in sorted(by_type.items())], reporting


def snapshot_from_docs(
    docs: Iterable[dict], contest_name: str, cmap: CandidateMap, race: str
) -> Snapshot:
    cells: list[Cell] = []
    reporting: dict[str, float] = {}
    complete: dict[tuple[str, str], float] = {}
    as_of = None
    for doc in docs:
        county_cells, frac = parse_county(doc, contest_name, cmap)
        if not county_cells:
            continue
        uid = county_cells[0].unit_id
        cells.extend(county_cells)
        if frac is not None:
            reporting[uid] = frac
        for vt, status in group_status(doc).items():
            complete[(uid, vt)] = status
        as_of = max(filter(None, [as_of, doc["election"].get("asOf")]), default=as_of)
    return Snapshot("GA", race, as_of, cells, reporting, complete, warnings=cmap.warnings())


def fetch_all(client: PoliteClient, election_code: str, base: str = BASE, workers: int = 4) -> list[dict]:
    """Statewide doc + every county doc. A few workers only: this is a state server."""
    state_doc = json.loads(client.get(data_url("Georgia", election_code, base)))
    shorts = [short for short, _ in counties(state_doc)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda s: json.loads(client.get(data_url(s, election_code, base))), shorts))


def save_archive(docs: list[dict], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        short = doc["jurisdiction"]["shortName"]
        (directory / f"{short}.json").write_text(json.dumps(doc))


def load_archive(directory: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(directory.glob("*.json"))]


# Adapter protocol (see adapters/__init__.py).

def fetch_source(client: PoliteClient, feed) -> list[dict]:
    return fetch_all(client, feed.election_id)


def parse(docs: list[dict], contest_name: str, cmap: CandidateMap, race: str) -> Snapshot:
    return snapshot_from_docs(docs, contest_name, cmap, race)


def final_snapshot(spec: dict, archives: Path, cmap: CandidateMap, key: str) -> Snapshot:
    return snapshot_from_docs(load_archive(archives / spec["code"]), spec["contest"], cmap, key)
