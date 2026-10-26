"""SC-1 (2026-SC-H01): county parts from the statewide Clarity file.

The fixture is the official 2024 statewide detail.xml (EID 122436) trimmed to the
header, the turnout block and the US House District 1 contest.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import pytest

from torehancast import config, elections
from torehancast.adapters import sc_clarity as sc
from torehancast.elections import ROOT

FIX = Path(__file__).parents[1] / "fixtures" / "sc" / "house"
CONTEST = "U.S.  House of Representatives, District  1"
SC1_PARTS = {"BEAUFORT", "BERKELEY", "CHARLESTON", "COLLETON", "DORCHESTER", "JASPER"}


def snapshot(text: str):
    spec = elections.load("SC", "2024_house_01")
    return sc.parse(text, spec.spec["contest"], spec.candidates, "2024_house_01")


def test_2024_county_parts_vote_types_and_official_totals():
    snap = snapshot(sc.load_archive(FIX, "122436"))

    assert snap.units() == SC1_PARTS
    assert {c.vote_type for c in snap.cells} == {"early", "mail", "election_day", "provisional"}
    # Certified totals: Mace 227,502, Moore 162,582, write-ins 693.
    assert snap.totals() == {"R": 227_502, "D": 162_582, "other": 693}
    assert snap.unit_reporting == {u: 1.0 for u in SC1_PARTS}


def test_reporting_is_the_county_part_not_the_whole_county():
    root = ET.fromstring(sc.load_archive(FIX, "122436"))
    contest = next(c for c in root.findall("Contest") if c.attrib["text"] == CONTEST)
    parts = {c.attrib["name"]: c for c in contest.findall("./ParticipatingCounties/County")}
    whole = {c.attrib["name"]: c for c in root.findall("./ElectionVoterTurnout/Counties/County")}
    # SC-1 has 79 of Charleston's precincts; the county has many more.
    assert parts["Charleston"].attrib["precinctsParticipating"] == "79"
    assert int(whole["Charleston"].attrib["precinctsParticipating"]) > 79

    parts["Charleston"].set("precinctsReported", "20")
    whole["Charleston"].set("precinctsReported", "0")
    snap = snapshot(ET.tostring(root, encoding="unicode"))
    assert snap.unit_reporting["CHARLESTON"] == pytest.approx(20 / 79)

    # Without the contest's own counts, the turnout block is the fallback.
    contest.remove(contest.find("ParticipatingCounties"))
    snap = snapshot(ET.tostring(root, encoding="unicode"))
    assert snap.unit_reporting["CHARLESTON"] == 0.0


def test_provionsal_typo_counts_as_provisional():
    root = ET.fromstring(sc.load_archive(FIX, "122436"))
    contest = next(c for c in root.findall("Contest") if c.attrib["text"] == CONTEST)
    for vt in contest.iter("VoteType"):
        if vt.attrib["name"] == "Provisional":
            vt.set("name", "Provionsal")
    snap = snapshot(ET.tostring(root, encoding="unicode"))
    assert {c.vote_type for c in snap.cells} == {"early", "mail", "election_day", "provisional"}
    assert snap.totals() == {"R": 227_502, "D": 162_582, "other": 693}


def test_committed_baseline_matches_the_official_file():
    snap = snapshot(sc.load_archive(FIX, "122436"))
    built = elections.to_frame(snap)
    committed = elections.read_baseline("SC", "2024_house_01")
    pd.testing.assert_frame_equal(built, committed, check_dtype=False)


def test_registry_row_points_at_the_house_baseline():
    loaded = config.load_config(ROOT / "config")
    race = loaded.races["2026-SC-H01"]
    assert (race.state, race.race_type, race.unit, race.baseline) == ("SC", "house", "county-part", "2024_house_01")
    assert elections.baseline_path("SC", race.baseline).exists()
    feed = loaded.feeds["2026-SC-H01"]
    assert feed.adapter == "sc_clarity"
