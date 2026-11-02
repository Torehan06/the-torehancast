"""Nebraska's results service, on rows saved from the live feed (Nov 2) and the state's archive."""

import copy
import json
from pathlib import Path

import pytest

from torehancast import config
from torehancast.adapters import ne_sos
from torehancast.candidates import CandidateMap
from torehancast.config import ResultsContest

FIX = Path(__file__).parents[1] / "fixtures" / "ne"
CANDIDATES = {"Dan Osborn": "D", "Pete Ricketts": "R"}


@pytest.fixture
def live():
    return json.loads((FIX / "live_20261102.json").read_text())


def counted(document, county="Adams", votes=100, reporting=11):
    """The saved zero-vote document with one county's rows counted."""
    document = copy.deepcopy(document)
    for key, rows in document.items():
        for i, row in enumerate(rows):
            if row["CountyName"] == county:
                row["calcCandidateVotes"] = votes * (i + 1)
                row["PrecinctsReporting"] = reporting
    return document


def test_zero_votes_means_no_cells(live):
    snap = ne_sos.parse(live, "SEN", CandidateMap(CANDIDATES), "2026-NE-SEN")
    assert snap.cells == [] and snap.totals() == {} and snap.unit_reporting == {}


def test_counts_collapse_names_and_report_precincts(live):
    snap = ne_sos.parse(counted(live), "SEN", CandidateMap(CANDIDATES), "2026-NE-SEN")
    assert snap.units() == {"ADAMS"}
    assert {"D", "R"} <= snap.totals().keys()  # "Pete  Ricketts " matched after collapsing spaces
    assert snap.cells[0].vote_type == "all"
    assert snap.unit_reporting == {"ADAMS": 11 / 22}
    assert any("Chuck Conboy" in w for w in snap.warnings)  # unlisted names pool into other


def test_a_missing_contest_is_empty_not_an_error(live):
    assert ne_sos.parse(live, "H9", CandidateMap(CANDIDATES), "x").cells == []


def test_results_only_totals_for_house_districts(live):
    contests = [ResultsContest(f"2026-NE-H0{n}", "house", n, "NE/sos", f"H{n}", {}) for n in (1, 2, 3)]
    found = ne_sos.parse_all_contests(counted(live, "Douglas", reporting=5), contests)
    h2 = found["2026-NE-H02"]
    assert set(h2.candidates.values()) == {"Brinker Harding", "Denise Powell", "Eric Michael Foreman"}
    assert h2.candidates["R"] == "Brinker Harding" and h2.candidates["D"] == "Denise Powell"
    assert sum(h2.votes.values()) > 0 and 0 < h2.pct_reporting < 1
    assert sum(found["2026-NE-H01"].votes.values()) == 0


def test_final_snapshot_reads_the_state_archive():
    spec = {"format": "state", "file": "23_8862.json"}
    cmap = CandidateMap({"Jane Raybould": "D", "Deb Fischer": "R", "Jim Schultz": "other"})
    snap = ne_sos.final_snapshot(spec, FIX, cmap, "2018_sen")
    assert snap.units() == {"ADAMS", "DOUGLAS"}
    totals = {c.unit_id: c.votes for c in snap.cells}
    assert totals["DOUGLAS"]["D"] > totals["DOUGLAS"]["R"]  # Omaha's county went to Raybould


def test_fetch_gets_every_listed_race_once():
    feed = config.load_config().feeds["2026-NE-SEN"]

    class Client:
        urls = []

        def get(self, url):
            self.urls.append(url)
            return b'{"d": [{"RaceID": 1}]}'

    document = ne_sos.fetch_source(Client(), feed)
    assert set(document) == {"SEN", "H1", "H2", "H3"}
    assert len(Client.urls) == 4 and "raceID=13224&osn=102" in Client.urls[0]
