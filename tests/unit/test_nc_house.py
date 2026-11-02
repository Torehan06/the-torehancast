"""NC-1 and NC-11: county parts from the SBE precinct files.

The fixtures are official SBE files trimmed to the rows these tests read: 2024 (all of
NC-11; Granville's House rows; President in Granville, Onslow and Tyrrell), 2020 (the
same President rows), 2022 (NC-11 in three counties), the Mar 2026 primary (the split
precincts) and the zero-vote Nov 2026 general (one row per choice per county of NC-1
and NC-11, except every row in Granville and Onslow).
"""

import copy
import csv
import io
from pathlib import Path

import pandas as pd
import pytest
import yaml

from torehancast import config, elections
from torehancast.adapters import nc_sbe as nc
from torehancast.candidates import CandidateMap
from torehancast.elections import ROOT
from torehancast.replay import harness

FIX = Path(__file__).parents[1] / "fixtures" / "nc" / "house"
HOUSE = "US HOUSE OF REPRESENTATIVES DISTRICT {:02d}"
LINES = yaml.safe_load((ROOT / "config" / "house" / "NC.yaml").read_text())["lines"]
NC01 = LINES["nc01_2026"]
PRES_2024 = {"Donald J. Trump": "R", "Kamala D. Harris": "D"}


def rows(date: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(nc.load_archive(FIX, date)), delimiter="\t"))


def votes(found: list[dict], contest: str, county: str | None = None, precinct: str | None = None) -> int:
    return sum(
        int(r["Total Votes"]) for r in found
        if r["Contest Name"] == contest and county in (None, r["County"]) and precinct in (None, r["Precinct"])
    )


def rebuilt(date: str, candidates: dict, lines: dict = NC01):
    return nc.parse(nc.load_archive(FIX, date), "US PRESIDENT", CandidateMap(candidates), "x", lines)


def by_county(frame: pd.DataFrame, county: str) -> pd.DataFrame:
    return frame[frame.unit_id == county].reset_index(drop=True)


def test_rebuild_matches_the_committed_baselines_on_the_fixture_counties():
    for key, date, candidates in (
        ("2024_pres_2026lines_01", "2024-11-05", PRES_2024),
        ("2020_pres_2026lines_01", "2020-11-03", {"Donald J. Trump": "R", "Joseph R. Biden": "D"}),
    ):
        built = elections.to_frame(rebuilt(date, candidates))
        committed = elections.read_baseline("NC", key)
        assert committed.unit_id.nunique() == 25
        for county in ("GRANVILLE", "ONSLOW", "TYRRELL"):
            pd.testing.assert_frame_equal(by_county(built, county), by_county(committed, county), check_dtype=False)


def test_a_whole_county_keeps_its_vote_center_rows():
    found = rows("2024-11-05")
    assert {r["Real Precinct"] for r in found if r["County"] == "TYRRELL" and r["Contest Name"] == "US PRESIDENT"} == {"Y", "N"}
    snap = rebuilt("2024-11-05", PRES_2024)
    tyrrell = sum(sum(c.votes.values()) for c in snap.cells if c.unit_id == "TYRRELL")
    assert tyrrell == votes(found, "US PRESIDENT", "TYRRELL")


def test_split_precincts_are_apportioned():
    found = rows("2024-11-05")
    snap = rebuilt("2024-11-05", PRES_2024)
    onslow = sum(sum(c.votes.values()) for c in snap.cells if c.unit_id == "ONSLOW")
    assert onslow == pytest.approx(0.726 * votes(found, "US PRESIDENT", "ONSLOW", "SW19"), abs=4)
    granville = sum(sum(c.votes.values()) for c in snap.cells if c.unit_id == "GRANVILLE")
    expected = sum(votes(found, "US PRESIDENT", "GRANVILLE", p) * s for p, s in NC01["parts"]["GRANVILLE"]["in"].items())
    assert granville == pytest.approx(expected, abs=4)


def test_shares_come_from_the_official_files():
    y2024 = rows("2024-11-05")
    def nc1_share(precinct):
        one = votes(y2024, HOUSE.format(1), "GRANVILLE", precinct)
        return one / (one + votes(y2024, HOUSE.format(13), "GRANVILLE", precinct))
    assert NC01["parts"]["GRANVILLE"]["in"]["SALM"] == round(nc1_share("SALM"), 3)
    assert NC01["parts"]["GRANVILLE"]["in"]["WOEL"] == round(nc1_share("WOEL"), 3)

    primary = rows("2026-03-03")
    def sw19(contest):
        return votes(primary, contest, "ONSLOW", "SW19")
    republicans_in = sw19(HOUSE.format(1) + " (REP)")
    senate_r, senate_d = sw19("US SENATE (REP)"), sw19("US SENATE (DEM)")
    democrats_in = senate_d - sw19(HOUSE.format(3) + " (DEM)")
    assert NC01["parts"]["ONSLOW"]["in"]["SW19"] == round((republicans_in + democrats_in) / (senate_r + senate_d), 3)


def test_split_county_precinct_lists_are_complete_with_nothing_unmatched():
    for date in ("2024-11-05", "2020-11-03"):
        assert nc.check_lines(nc.load_archive(FIX, date), "US PRESIDENT", NC01) == {"GRANVILLE": 0.0, "ONSLOW": 0.0}


def test_an_unknown_precinct_over_the_limit_fails_loudly():
    lines = copy.deepcopy(NC01)
    # As if WILT (16% of Granville's 2024 vote) had been renamed: its votes have no home.
    lines["parts"]["GRANVILLE"]["out"].remove("WILT")
    with pytest.raises(ValueError, match="GRANVILLE"):
        nc.check_lines(nc.load_archive(FIX, "2024-11-05"), "US PRESIDENT", lines)


def test_a_small_unknown_precinct_is_reported_not_fatal(monkeypatch):
    lines = copy.deepcopy(NC01)
    lines["parts"]["GRANVILLE"]["out"].remove("OKHL")
    found = rows("2024-11-05")
    share = votes(found, "US PRESIDENT", "GRANVILLE", "OKHL") / votes(found, "US PRESIDENT", "GRANVILLE")
    monkeypatch.setattr(nc, "MAX_UNMATCHED_SHARE", 0.05)
    assert nc.check_lines(nc.load_archive(FIX, "2024-11-05"), "US PRESIDENT", lines)["GRANVILLE"] == pytest.approx(share)


def test_a_named_precinct_missing_from_the_file_fails_at_any_size():
    lines = copy.deepcopy(NC01)
    lines["parts"]["ONSLOW"]["in"]["NOPE"] = 0.5
    with pytest.raises(ValueError, match="NOPE"):
        nc.check_lines(nc.load_archive(FIX, "2024-11-05"), "US PRESIDENT", lines)


def test_nc11_2024_county_parts_and_official_totals():
    spec = elections.load("NC", "2024_house_11")
    snap = nc.parse(nc.load_archive(FIX, "2024-11-05"), spec.spec["contest"], spec.candidates, spec.key)
    assert snap.totals() == {"R": 245_546, "D": 186_977}
    assert len(snap.units()) == 16
    pd.testing.assert_frame_equal(elections.to_frame(snap), elections.read_baseline("NC", spec.key), check_dtype=False)


def test_nc11_replay_uses_only_counties_whole_in_both_years():
    spec = elections.load("NC", "2022_house_11_common")
    assert spec.spec["lines"] == LINES["nc11_common"]
    text = nc.load_archive(FIX, "2022-11-08")
    snap = nc.parse(text, spec.spec["contest"], spec.candidates, spec.key, spec.spec["lines"])
    assert snap.units() == {"CLAY", "GRAHAM"}  # Rutherford's 2022 part is out
    committed = elections.read_baseline("NC", spec.key)
    built = elections.to_frame(snap)
    for county in ("CLAY", "GRAHAM"):
        pd.testing.assert_frame_equal(by_county(built, county), by_county(committed, county), check_dtype=False)
    assert set(committed.unit_id) == set(elections.read_baseline("NC", "2024_house_11_common").unit_id)
    assert set(committed.unit_id) <= set(elections.read_baseline("NC", "2024_house_11").unit_id)
    assert not {"AVERY", "MITCHELL", "POLK", "RUTHERFORD"} & set(committed.unit_id)


@pytest.mark.parametrize("race_id,n,baseline,parts", [
    ("2026-NC-H01", 1, "2024_pres_2026lines_01", 25),
    ("2026-NC-H11", 11, "2024_house_11", 16),
])
def test_registry_feed_and_general_file_agree(race_id, n, baseline, parts):
    loaded = config.load_config(ROOT / "config")
    race, feed = loaded.races[race_id], loaded.feeds[race_id]
    assert (race.state, race.race_type, race.unit, race.baseline) == ("NC", "house", "county-part", baseline)
    assert race.tau_pair == ("2020_pres", "2024_pres")
    assert (feed.status, feed.adapter, feed.url) == ("ready", "nc_sbe", loaded.feeds["2026-NC-SEN"].url)

    # Exact strings in the zero-vote 2026 general, and the results-only template's form.
    contest = HOUSE.format(n)
    assert feed.contest == contest
    general = rows("2026-11-03")
    assert {r["Choice"] for r in general if r["Contest Name"] == contest} == set(feed.candidates)
    assert {r["Choice Party"]: feed.candidates[r["Choice"]] for r in general if r["Contest Name"] == contest and r["Choice Party"] != "LIB"} == {"DEM": "D", "REP": "R"}

    # The feed's counties are the baseline's, in the same county-part units.
    snap = nc.parse(nc.load_archive(FIX, "2026-11-03"), feed.contest, CandidateMap(feed.candidates), race_id)
    assert sum(snap.totals().values()) == 0
    live = harness.to_race_units(race_id, snap, race.unit)
    base = harness.race_baseline(race_id, baseline, race.unit)
    assert live.units() == set(base.unit_id)
    assert len(live.units()) == parts
    assert all(u.endswith(f"|{n:02d}") for u in live.units())


def test_the_general_file_lists_the_split_precincts_in_nc1():
    general = rows("2026-11-03")
    def listed(county):
        return {r["Precinct"] for r in general if r["Contest Name"] == HOUSE.format(1) and r["County"] == county}
    assert listed("GRANVILLE") == set(NC01["parts"]["GRANVILLE"]["in"])
    assert listed("ONSLOW") == set(NC01["parts"]["ONSLOW"]["in"])
