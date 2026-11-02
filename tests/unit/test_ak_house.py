"""2026-AK-HAL: the at-large House race on Alaska's shared Division of Elections feed.

The fixture is the real certified Aug 2026 primary file, cut to the "U.S. Representative"
rows for Districts 1, 38 and the overseas unit 99.
"""

import csv
import io
from collections import Counter
from pathlib import Path

from torehancast import elections
from torehancast.adapters import ak_doe as ak
from torehancast.candidates import CandidateMap
from torehancast.config import load_config

FIX = Path(__file__).parents[1] / "fixtures" / "ak" / "house"
HOUSE = "U.S. Representative"
RACE = "2026-AK-HAL"


def _rows() -> list[dict]:
    text = ak.load_archive(FIX, "26PRIM")
    return [r for r in csv.DictReader(io.StringIO(text)) if r["Contest_title"] == HOUSE]


def _spec() -> dict:
    return elections.load("AK", "2026_prim_house").spec


def test_fixture_is_the_house_contest_only():
    rows = _rows()
    assert len(rows) == sum(1 for _ in csv.DictReader(io.StringIO(ak.load_archive(FIX, "26PRIM"))))
    assert {ak.locate(r["Precinct_name"])[0] for r in rows} == {"1", "38", "99"}


def test_every_configured_name_is_on_the_primary_ballot_exactly():
    on_ballot = {r["candidate_name"] for r in _rows()}
    assert set(_spec()["candidates"]) <= on_ballot


def test_blocs_are_every_republican_and_every_democrat_plus_hill():
    party = {r["candidate_name"]: r["Party_Code"] for r in _rows()}
    sides = _spec()["candidates"]
    assert {n for n, p in party.items() if p == "REP"} == {n for n, s in sides.items() if s == "R"}
    assert {n for n, p in party.items() if p == "DEM"} | {"Hill, Bill"} == {n for n, s in sides.items() if s == "D"}
    # Hill is the only nonpartisan name given a side; the Libertarian is "other".
    assert party["Hill, Bill"] == "NON"
    assert not {n for n, p in party.items() if p in ("NON", "UND", "LIB")} - {"Hill, Bill"} & set(sides)


def test_parse_books_bloc_totals_by_district_and_vote_type():
    rows = _rows()
    snap = ak.parse(ak.load_archive(FIX, "26PRIM"), HOUSE, CandidateMap(_spec()["candidates"]), RACE)

    expected = Counter()
    for r in rows:
        expected[_spec()["candidates"].get(r["candidate_name"], "other")] += int(r["total_votes"])
    assert snap.totals() == {k: v for k, v in expected.items() if v}
    assert snap.units() == {"1", "38", "99"}
    assert {c.vote_type for c in snap.cells if c.unit_id == "99"} == {"mail"}
    assert snap.unit_reporting == {"1": 1.0, "38": 1.0}
    assert any("McDermott" in w for w in snap.warnings)


def test_live_feed_shares_the_senate_source_and_the_baseline_blocs():
    cfg = load_config()
    house, senate = cfg.feeds[RACE], cfg.feeds["2026-AK-SEN"]
    assert (house.adapter, house.url) == (senate.adapter, senate.url)
    assert house.contest == HOUSE
    assert house.candidates == _spec()["candidates"]
    assert house.display == {"D": "Bill Hill", "R": "Nick Begich"}
    assert (house.candidates["Hill, Bill"], house.candidates["Begich, Nick"]) == ("D", "R")

    race = cfg.races[RACE]
    assert race.ranked_choice and race.unit == "house-district"
    assert race.baseline == "2026_prim_house"
    assert race.tau_pair == ("2024_prim_house", "2024_gen_house")


def test_baseline_csv_covers_every_district_and_matches_the_certified_totals():
    df = elections.read_baseline("AK", "2026_prim_house")
    assert set(df.unit_id) == {str(n) for n in range(1, 41)} | {"99"}
    # Certified Aug 18, 2026 primary: Hill + Democrats 79,673; Republicans 77,320.
    assert (df.D.sum(), df.R.sum()) == (79_673, 77_320)
