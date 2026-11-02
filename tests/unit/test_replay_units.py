"""County-part units and race-keyed replay config (W7 foundation). No archives needed."""

import pandas as pd
import pytest

from torehancast.replay import arrivals, harness, units
from torehancast.schema import Cell, Snapshot


def test_county_part_keys_round_trip():
    assert units.county_part("POLK", 3) == "POLK|03"
    assert units.county_part("POLK|03", 3) == "POLK|03"  # already a part: unchanged
    assert units.county_of("POLK|03") == "POLK"
    assert units.county_of("O'BRIEN") == "O'BRIEN"


def test_relabel_moves_every_unit_keyed_field():
    snap = Snapshot("NC", "x", "t", [Cell("WAKE", "early", {"D": 3, "R": 1})], {"WAKE": 0.5},
                    {("WAKE", "early"): 1.0}, ["w"])
    out = units.relabel(snap, 13)
    assert out.units() == {"WAKE|13"}
    assert out.unit_reporting == {"WAKE|13": 0.5}
    assert out.cell_complete == {("WAKE|13", "early"): 1.0}
    assert out.warnings == ["w"] and out.cells[0].votes == {"D": 3, "R": 1}


def test_split_county_parts_inherit_their_county_demographics():
    demo = pd.DataFrame({"unit_id": ["WAKE", "DURHAM"], "white_nh": [0.6, 0.4], "median_age": [36.0, 35.0]})
    out = units.demographics_for(demo, ["WAKE|13", "WAKE|02", "DURHAM|04"])
    assert list(out.unit_id) == ["DURHAM|04", "WAKE|02", "WAKE|13"]
    assert list(out.white_nh) == [0.4, 0.6, 0.6]
    assert list(out.columns) == ["unit_id", "white_nh", "median_age"]


def test_a_county_without_demographics_is_an_error_not_the_state_mean():
    demo = pd.DataFrame({"unit_id": ["WAKE"], "white_nh": [0.6]})
    with pytest.raises(ValueError, match="DURHAM"):
        units.demographics_for(demo, ["WAKE|13", "DURHAM|04"])


def test_late_close_applies_to_every_part_of_a_late_county():
    cells = [Cell(u, "election_day", {"D": 100, "R": 100}) for u in ("BAY|02", "LEON|02")]
    final = Snapshot("FL", "x", None, cells, {})
    profile = arrivals.Profile(late_close={"hours": 50.0, "units": ["BAY"]})
    first = {}
    for e in arrivals.timeline(final, "timezone", 0, profile):
        first.setdefault(e.unit_id, e.time)
    assert first["BAY|02"] >= 50.0 > first["LEON|02"]


def test_race_keys_resolve_and_inherit_state_traits():
    assert harness.resolve("2026-GA-SEN") == "GA"
    assert harness.resolve("2026-FL-SEN-SPECIAL") == "FL"
    assert harness.resolve("2026-IA-H01") == "2026-IA-H01"
    assert harness.replay_config("2026-GA-SEN") == harness.replay_config("GA")
    cfg = harness.replay_config("2026-IA-H01")
    assert cfg["batch_vote_types"] == ["early"]  # Iowa's trait, inherited
    assert cfg["primary"]["units"] == "2024_house_01"  # its own pair, not the state's
    assert harness.state_of("2026-IA-H01") == "IA"


def test_replay_keys_list_states_then_house_races():
    keys = harness.replay_keys()
    assert keys[:7] == ["GA", "NC", "FL", "SC", "MN", "IA", "AK"]
    assert {"2026-IA-H01", "2026-IA-H02", "2026-IA-H03"} <= set(keys)


def test_unit_scheme_comes_from_races_yaml_unless_given():
    assert harness.unit_scheme("GA") == (units.COUNTY, None)
    assert harness.unit_scheme("2026-IA-H02") == (units.COUNTY_PART, 2)
    assert harness.unit_scheme("2026-IA-H02", "county") == ("county", 2)
