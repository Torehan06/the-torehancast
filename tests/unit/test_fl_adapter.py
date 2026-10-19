import csv
import io
from pathlib import Path

import pytest

from torehancast.adapters import fl_dos as fl
from torehancast.candidates import CandidateMap
from torehancast.schema import ALL, Cell, Snapshot

FIX = Path(__file__).parents[1] / "fixtures" / "fl"


def test_parses_all_counties_and_pools_other_candidates():
    text = fl.load_archive(FIX, "2024-11-05")
    cmap = CandidateMap({"Scott, Rick": "R", "Mucarsel-Powell, Debbie": "D"})
    snap = fl.parse(text, "USS", cmap, "2024_sen")

    assert snap.state == "FL"
    assert snap.race == "2024_sen"
    assert len(snap.cells) == 67
    assert {c.vote_type for c in snap.cells} == {"all"}
    assert all(frac == pytest.approx(1.0) for frac in snap.unit_reporting.values())
    assert cmap.unmatched == {
        "Bonoan, Feena",
        "Everidge, Ben",
        "Knepper, Howard",
        "Nguyen, Tuan",
    }
    assert all("other" in c.votes for c in snap.cells)


@pytest.mark.parametrize(
    ("election_date", "candidates"),
    [
        ("2018-11-06", {"Scott, Rick": "R", "Nelson, Bill": "D"}),
        ("2024-11-05", {"Scott, Rick": "R", "Mucarsel-Powell, Debbie": "D"}),
    ],
)
def test_county_totals_match_the_extracts_own_rows(election_date, candidates):
    text = fl.load_archive(FIX, election_date)
    cmap = CandidateMap(candidates)
    snap = fl.parse(text, "USS", cmap, "fl_sen")

    expected_r = 0
    expected_d = 0
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        if row["RaceCode"] != "USS":
            continue
        side = candidates.get(fl.ballot_name(row))
        if side == "R":
            expected_r += int(row["CanVotes"])
        elif side == "D":
            expected_d += int(row["CanVotes"])

    totals = snap.totals()
    assert totals["R"] == expected_r
    assert totals["D"] == expected_d


def test_missing_race_code_yields_no_cells():
    text = fl.load_archive(FIX, "2024-11-05")
    snap = fl.parse(text, "USS-SPECIAL", CandidateMap({}), "2024_sen")
    assert snap.cells == []
    assert snap.unit_reporting == {}


def test_form_and_ballot_name():
    assert fl.form("2024-11-05", official=False) == {
        "ElectionDate": "11/5/2024",
        "OfficialResults": "N",
        "PartyRaces": "N",
        "DataMode": "",
        "FormsButton2": "Download",
    }
    assert fl.ballot_name({"CanNameLast": " Mucarsel-Powell ", "CanNameFirst": " Debbie "}) == (
        "Mucarsel-Powell, Debbie"
    )


def test_batch_tracker_splits_real_fixture_across_two_polls():
    text = fl.load_archive(FIX, "2024-11-05")
    cmap = CandidateMap({"Scott, Rick": "R", "Mucarsel-Powell, Debbie": "D"})
    final = fl.parse(text, "USS", cmap, "2024_sen")

    # Simulate the pre-Election-Day batch (half of each county's votes posted with 0 precincts reporting)
    early_cells = [
        Cell(c.unit_id, ALL, {k: v // 2 for k, v in c.votes.items()})
        for c in final.cells
    ]
    pre_ed = Snapshot("FL", "2024_sen", None, early_cells, {c.unit_id: 0.0 for c in final.cells})

    tracker = fl.BatchTracker()
    snap1 = tracker.split(pre_ed)
    assert {c.vote_type for c in snap1.cells} == {"early"}
    assert all(snap1.cell_complete[(c.unit_id, "early")] == 1.0 for c in final.cells)

    snap2 = tracker.split(final)
    assert {c.vote_type for c in snap2.cells} == {"early", "election_day"}
    assert snap2.totals() == final.totals()
