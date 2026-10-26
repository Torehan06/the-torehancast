"""Iowa: Secretary of State Clarity results (`electionresults.iowa.gov`).

Iowa publishes statewide and county election results on Clarity:

    https://electionresults.iowa.gov/IA/{election_id}/current_ver.txt
    https://electionresults.iowa.gov/IA/{election_id}/{version}/reports/detailxml.zip

Every statewide Iowa election is allocated a block of 100 consecutive Clarity IDs:
`{election_id}` for the statewide rollup (e.g. `122322` in 2024, `106279` in 2020)
followed by `{election_id + 1}`..`{election_id + 99}` for Adair..Wright counties.
Each contest in `detail.xml` reports two `<VoteType>` buckets per county:
`"Election Day"` (`election_day`) and `"Absentee"` (`early`, combining early
in-person and mail absentee ballots).
"""

from __future__ import annotations

from ..candidates import CandidateMap
from ..http import PoliteClient
from ..schema import Snapshot
from . import sc_clarity

BASE = "https://electionresults.iowa.gov/IA"

read_zip = sc_clarity.read_zip
unit_id = sc_clarity.unit_id
load_archive = sc_clarity.load_archive


def version_url(election_id: str | int, base: str = BASE) -> str:
    return sc_clarity.version_url(election_id, base)


def results_url(election_id: str | int, version: str | int, base: str = BASE) -> str:
    return sc_clarity.results_url(election_id, version, base)


def fetch(client: PoliteClient, election_id: str | int, base: str = BASE) -> str:
    return sc_clarity.fetch(client, election_id, base)


def parse(xml_text: str, contest_name: str, cmap: CandidateMap, race: str) -> Snapshot:
    return sc_clarity.parse(xml_text, contest_name, cmap, race, state="IA")


# Adapter protocol (see adapters/__init__.py).

def fetch_source(client: PoliteClient, feed) -> str:
    return fetch(client, feed.election_id)


def final_snapshot(spec: dict, archives, cmap: CandidateMap, key: str) -> Snapshot:
    return parse(load_archive(archives, spec["election_id"]), spec["contest"], cmap, key)
