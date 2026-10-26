"""South Carolina: State Election Commission Clarity results (`enr-scvotes.org`).

South Carolina publishes statewide and county election results on Clarity:

    https://www.enr-scvotes.org/SC/{election_id}/current_ver.txt
    https://www.enr-scvotes.org/SC/{election_id}/{version}/reports/detailxml.zip

Inside `detailxml.zip` is `detail.xml`, which carries `<ElectionVoterTurnout>`
with per-county precinct reporting counts and `<Contest>` elements broken down by
`<Choice>`, `<VoteType>` and `<County>`. For a district contest each `<County>` is
the county's part of the district (e.g. SC-1's share of Charleston). Multiple raw vote-type buckets (e.g.
"Provisional", "Failsafe", "Failsafe Provisional", and the 2024 typo "Provionsal")
map to canonical `provisional` and are summed per `(unit_id, vote_type)`.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path

from ..candidates import CandidateMap
from ..http import PoliteClient
from ..schema import Cell, Snapshot, canonical_vote_type

BASE = "https://www.enr-scvotes.org/SC"


def version_url(election_id: str | int, base: str = BASE) -> str:
    return f"{base}/{election_id}/current_ver.txt"


def results_url(election_id: str | int, version: str | int, base: str = BASE) -> str:
    return f"{base}/{election_id}/{version}/reports/detailxml.zip"


def read_zip(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = "detail.xml" if "detail.xml" in zf.namelist() else next(n for n in zf.namelist() if n.endswith(".xml"))
        return zf.read(name).decode("utf-8", errors="replace")


def fetch(client: PoliteClient, election_id: str | int, base: str = BASE) -> str:
    version = client.get(version_url(election_id, base)).decode("utf-8", errors="replace").strip()
    return read_zip(client.get(results_url(election_id, version, base)))


def unit_id(county_name: str) -> str:
    return county_name.strip().upper().removesuffix(" COUNTY").strip()


def parse(xml_text: str, contest_name: str, cmap: CandidateMap, race: str, state: str = "SC") -> Snapshot:
    root = ET.fromstring(xml_text)
    as_of = root.findtext("Timestamp")
    contest = next((c for c in root.findall("Contest") if c.attrib.get("text") == contest_name), None)
    if contest is None:
        return Snapshot(state, race, as_of, [], {}, warnings=cmap.warnings())

    votes: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    contest_units: set[str] = set()
    for choice in contest.findall("Choice"):
        key = cmap.key_for(choice.attrib["text"])
        for vt_el in choice.findall("VoteType"):
            vt = canonical_vote_type(vt_el.attrib["name"])
            for county_el in vt_el.findall("County"):
                uid = unit_id(county_el.attrib["name"])
                contest_units.add(uid)
                votes[(uid, vt)][key] += int(county_el.attrib.get("votes") or 0)

    # A district contest (e.g. US House SC-1) covers only part of some counties, so its
    # own <ParticipatingCounties> precinct counts are the county part's reporting.
    # For a statewide contest they match the turnout block, which is the fallback.
    reporting: dict[str, float] = {}
    turnout_counties = (
        contest.findall("./ParticipatingCounties/County")
        or root.findall("./ElectionVoterTurnout/Counties/County")
        or root.findall("./VoterTurnout/Counties/County")
    )
    for county_el in turnout_counties:
        uid = unit_id(county_el.attrib["name"])
        if uid not in contest_units:
            continue
        total = int(county_el.attrib.get("precinctsParticipating") or 0)
        if total > 0:
            reported = int(county_el.attrib.get("precinctsReported") or 0)
            reporting[uid] = reported / total

    cells = [Cell(uid, vt, dict(v)) for (uid, vt), v in sorted(votes.items())]
    return Snapshot(state, race, as_of, cells, reporting, warnings=cmap.warnings())


def load_archive(directory: Path, election_id: str | int) -> str:
    return (directory / f"{election_id}_detail.xml").read_text(encoding="utf-8", errors="replace")


# Adapter protocol (see adapters/__init__.py).

def fetch_source(client: PoliteClient, feed) -> str:
    return fetch(client, feed.election_id)


def final_snapshot(spec: dict, archives: Path, cmap: CandidateMap, key: str) -> Snapshot:
    return parse(load_archive(archives, spec["election_id"]), spec["contest"], cmap, key)
