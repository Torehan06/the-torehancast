"""Ohio's NIST 1500-100 feed, on a cut of the real Nov 3, 2026 document (Oct 30 copy).

That copy is all zeros, so the tests write counts into it. The cut keeps every county
GpUnit, including the "Adams County" court-district twins that have no precinct counts,
plus U.S. Senator, District 03 (Franklin only) and District 09.
"""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import pytest

from torehancast import adapters, elections, public_json, publish
from torehancast.adapters import oh_sos
from torehancast.adapters.fl_dos import BatchTracker
from torehancast.candidates import CandidateMap
from torehancast.config import ResultsContest
from torehancast.elections import ROOT
from torehancast.model.simulate import RacePrior
from torehancast.replay import harness

FIXTURE = Path(__file__).parents[1] / "fixtures" / "oh" / "oh_nist_20261030.xml"
NS = oh_sos.NS
SENATE = {"Sherrod Brown": "D", "Jon Husted": "R", "Greg Levy": "other", "William Redpath": "other",
          "Stephen Faris": "other", "Anthony Holliman": "other", "Timothy Telymonde": "other"}
H03, H09 = ("Representative to Congress - District 03", "Representative to Congress - District 09")


def contest(race_id, n, name, sides=None):
    return ResultsContest(race_id, "house", n, "OH/x", name, sides or {})


SENATE_CONTEST = ResultsContest("2026-OH-SEN-SPECIAL", "senate-special", None, "OH/x", "U.S. Senator", {})


def with_counts(xml, contest_name, by_candidate, reporting=None):
    """Every county line of each named candidate gets that count; aggregates get the sum."""
    root = ET.fromstring(xml)
    units = {u.attrib["ObjectId"]: u for u in root.find(f"{NS}GpUnitCollection")}
    election = root.find(f"{NS}Election")
    names = {c.attrib["ObjectId"]: c.findtext(f"{NS}BallotName/{NS}LanguageString")
             for c in election.find(f"{NS}CandidateCollection")}
    for c in election.find(f"{NS}ContestCollection"):
        if c.attrib["Name"] != contest_name:
            continue
        for selection in c.findall(f"{NS}BallotSelection"):
            n = by_candidate.get(names[selection.findtext(f"{NS}CandidateId")], 0)
            lines = list(selection.iter(f"{NS}VoteCounts"))
            counties = [v for v in lines if "TotalSubUnits" in units[v.findtext(f"{NS}GpUnitId")].attrib]
            for v in lines:
                v.attrib["Count"] = str(n * len(counties) if v not in counties else n)
    for name, (r, t) in (reporting or {}).items():
        for u in units.values():
            if u.attrib.get("Name") == name:
                u.attrib.update(SubUnitsReported=str(r), TotalSubUnits=str(t))
    return ET.tostring(root, encoding="unicode")


@pytest.fixture(scope="module")
def feed():
    return FIXTURE.read_text()


def test_parses_all_88_counties_and_matches_demographics(feed):
    snap = oh_sos.parse(feed, "U.S. Senator", CandidateMap(SENATE), "race")
    demo = pd.read_csv(ROOT / "data" / "demographics" / "OH.csv")
    assert {c.unit_id for c in snap.cells} == set(demo["unit_id"]) and len(snap.cells) == 88
    assert snap.as_of == "2026-10-30T08:48:15Z"
    assert all(c.vote_type == "all" and c.total == 0 for c in snap.cells)


def test_only_county_lines_are_summed_never_the_aggregate(feed):
    xml = with_counts(feed, "U.S. Senator", {"Sherrod Brown": 10, "Jon Husted": 7, "Greg Levy": 1})
    snap = oh_sos.parse(xml, "U.S. Senator", CandidateMap(SENATE), "race")
    assert snap.totals() == {"D": 880, "R": 616, "other": 88}
    assert next(c for c in snap.cells if c.unit_id == "VAN WERT").votes == {"D": 10, "R": 7, "other": 1}


def test_court_district_twins_are_not_units(feed):
    snap = oh_sos.parse(feed, "U.S. Senator", CandidateMap(SENATE), "race")
    assert not [c for c in snap.cells if c.unit_id.endswith(" COUNTY")]
    assert not [u for u in snap.unit_reporting if u.endswith(" COUNTY")]


def test_precinct_reporting_per_county(feed):
    xml = with_counts(feed, "U.S. Senator", {"Sherrod Brown": 1}, reporting={"Franklin": (222, 888)})
    snap = oh_sos.parse(xml, "U.S. Senator", CandidateMap(SENATE), "race")
    assert snap.unit_reporting["FRANKLIN"] == 0.25 and snap.unit_reporting["ADAMS"] == 0.0


def test_test_flag_becomes_a_warning_and_clears(feed):
    assert "feed is marked IsTest: test data" in oh_sos.parse(feed, "U.S. Senator", CandidateMap(SENATE), "r").warnings
    live = feed.replace('IsTest="true"', 'IsTest="false"')
    assert oh_sos.parse(live, "U.S. Senator", CandidateMap(SENATE), "r").warnings == []


def test_unknown_ballot_name_is_pooled_with_a_warning(feed):
    snap = oh_sos.parse(feed, "U.S. Senator", CandidateMap({"Sherrod Brown": "D", "Jon Husted": "R"}), "r")
    assert any("Greg Levy" in w for w in snap.warnings)


def test_missing_contest_is_an_empty_snapshot(feed):
    assert oh_sos.parse(feed, "No Such Contest", CandidateMap({}), "r").cells == []


def test_results_only_senate_reports_statewide_precincts(feed):
    xml = with_counts(feed, "U.S. Senator", {"Sherrod Brown": 10, "Jon Husted": 7, "William Redpath": 2, "Stephen Faris": 1})
    t = oh_sos.parse_all_contests(xml, [SENATE_CONTEST])["2026-OH-SEN-SPECIAL"]
    assert t.candidates == {"D": "Sherrod Brown", "R": "Jon Husted", "L": "William Redpath", "other": "Other candidates"}
    assert t.votes == {"D": 880, "R": 616, "L": 176, "other": 88}  # the write-in pools into other
    assert t.pct_reporting == 0.0 and t.as_of == "2026-10-30T08:48:15Z"
    done = re.sub(r'SubUnitsReported="\d+" TotalSubUnits="(\d+)"', r'SubUnitsReported="\1" TotalSubUnits="\1"', xml)
    assert oh_sos.parse_all_contests(done, [SENATE_CONTEST])["2026-OH-SEN-SPECIAL"].pct_reporting == 1.0


def test_district_contests_publish_no_reporting_fraction(feed):
    # A county's precinct counts cover the whole county, not the district's part of it.
    xml = with_counts(feed, H09, {"Marcy Kaptur": 5, "Derek Merrin": 3})
    found = oh_sos.parse_all_contests(xml, [contest("2026-OH-H09", 9, H09), contest("2026-OH-H03", 3, H03),
                                            contest("2026-OH-H02", 2, "Representative to Congress - District 02")])
    assert set(found) == {"2026-OH-H09", "2026-OH-H03"}  # District 02 isn't in this cut: no votes yet
    h09 = found["2026-OH-H09"]
    assert h09.pct_reporting is None
    assert h09.candidates["D"] == "Marcy Kaptur" and h09.votes["D"] % 5 == 0 and h09.votes["D"] > 0
    assert h09.votes["D"] / h09.votes["R"] == pytest.approx(5 / 3)


def test_registered_with_the_adapter_protocol():
    module = adapters.get("oh_sos")
    assert all(hasattr(module, f) for f in ("fetch_source", "parse", "final_snapshot", "parse_all_contests"))


@pytest.mark.parametrize("key, d, r", [("2012_sen", 2762766, 2435744), ("2018_sen", 2358508, 2057559),
                                       ("2024_sen", 2650949, 2857383)])
def test_committed_baselines_match_published_statewide_totals(key, d, r):
    df = elections.read_baseline("OH", key)
    assert (int(df.D.sum()), int(df.R.sum())) == (d, r) and len(df) == 88


def test_absentee_batch_with_no_precincts_runs_through_tracker_model_and_publisher(feed, tmp_path):
    prior = RacePrior(0.01, 0.06, 0.75, 0.10)
    model = harness.make_model("OH", "2024_sen", ("2018_sen", "2024_sen"), prior, harness.live_synthetic_split("OH"))
    tracker = BatchTracker()
    cmap = CandidateMap(SENATE)
    night = feed.replace('IsTest="true"', 'IsTest="false"')

    # 7:45 pm: every county has posted its absentee batch, with 0 precincts reporting.
    first = with_counts(night, "U.S. Senator", {"Sherrod Brown": 1000, "Jon Husted": 900, "William Redpath": 20})
    snap = tracker.split(oh_sos.parse(first, "U.S. Senator", cmap, "2026-OH-SEN-SPECIAL"))
    assert {c.vote_type for c in snap.cells} == {"early"} and all(v == 1.0 for v in snap.cell_complete.values())

    # Later: precincts are in for Franklin, so what it adds is booked as Election Day.
    later = with_counts(night, "U.S. Senator", {"Sherrod Brown": 1100, "Jon Husted": 1200, "William Redpath": 25},
                        reporting={"Franklin": (889, 889)})
    snap = tracker.split(oh_sos.parse(later, "U.S. Senator", cmap, "2026-OH-SEN-SPECIAL"))
    franklin = {c.vote_type: c.votes for c in snap.cells if c.unit_id == "FRANKLIN"}
    assert franklin["early"]["D"] == 1000 and franklin["election_day"] == {"D": 100, "R": 300, "other": 5}

    update = publish.StateUpdate("OH", "2026-OH-SEN-SPECIAL", {"D": "Sherrod Brown", "R": "Jon Husted"},
                                 model.run(snap, 500, 0), model, snap.as_of, votes=snap.totals(),
                                 race_type="senate-special", district=None, ranked_choice=False)
    publish.publish([update], publish.LocalWriter(tmp_path / "out"), mode="live")
    payload = json.loads((tmp_path / "out/data/live/summary.json").read_text())["states"][0]
    assert payload["modeled"] is True and set(payload["p_win"]) == {"D", "R"}
    assert payload["votes"] == {"D": snap.totals()["D"], "R": snap.totals()["R"]}
    priors = tmp_path / "priors.yaml"
    priors.write_text("priors:\n  2026-OH-SEN-SPECIAL:\n    margin: 0.0123457\n    margin_sd: 0.0612346\n"
                      "    turnout_ratio: 0.7512346\n    turnout_sd: 0.1012346\n")
    assert public_json.check_tree(tmp_path / "out", priors=priors, mode="live").private_values_checked

