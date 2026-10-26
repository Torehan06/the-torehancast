"""Florida House: district contests in the DOS extract (`RaceCode=USR`, district in `Juris1num`).

The fixture is every USR row of the certified 2024 extract (old lines; the parsing is
the same for the 2026 file).
"""

from pathlib import Path

import pytest

from torehancast.adapters import fl_dos as fl
from torehancast.candidates import CandidateMap

FIX = Path(__file__).parents[1] / "fixtures" / "fl"
TEXT = (FIX / "usr_20241105.txt").read_text(encoding="latin-1")


def test_contest_filter_reads_race_code_and_district():
    assert fl.contest_filter("USS") == ("USS", None)
    assert fl.contest_filter("USR:022") == ("USR", 22)
    assert fl.contest_filter("USR:9") == ("USR", 9)


def test_district_contest_yields_its_county_parts_only():
    cmap = CandidateMap({"Chalifoux, Thomas": "R", "Soto, Darren": "D"})
    snap = fl.parse(TEXT, "USR:009", cmap, "2024_house_09")

    assert [c.unit_id for c in snap.cells] == ["ORANGE", "OSCEOLA", "POLK"]
    by_unit = {c.unit_id: c.votes for c in snap.cells}
    assert by_unit["OSCEOLA"] == {"R": 74399, "D": 90405, "other": 3928}
    assert by_unit["POLK"] == {"R": 10079, "D": 14802, "other": 458}
    assert snap.unit_reporting == {"ORANGE": 1.0, "OSCEOLA": 1.0, "POLK": 1.0}
    assert cmap.unmatched == {"Carter, Marcus"}


def test_split_county_counts_only_its_part_in_each_district():
    # Pinellas is split between FL-13 and FL-14 on the 2022 lines.
    cmap14 = CandidateMap({"Rochford, Robert": "R", "Castor, Kathy": "D"})
    snap14 = fl.parse(TEXT, "USR:014", cmap14, "h14")
    assert {c.unit_id: c.votes["D"] for c in snap14.cells} == {"HILLSBOROUGH": 138203, "PINELLAS": 61220}

    # The middle name is not part of the ballot name ("Luna, Anna", not "Anna Paulina").
    cmap13 = CandidateMap({"Luna, Anna": "R", "Fox, Whitney": "D"})
    snap13 = fl.parse(TEXT, "USR:013", cmap13, "h13")
    assert [c.unit_id for c in snap13.cells] == ["PINELLAS"]
    assert snap13.cells[0].votes == {"R": 225636, "D": 185930, "other": 27}

    # Each part reports against its own precincts: 229 + 57 of Pinellas's 286.
    rows = [line.split("\t") for line in TEXT.splitlines()[1:]]
    parts = {int(r[7]): int(r[9]) for r in rows if r[5] == "PIN"}
    assert parts == {13: 229, 14: 57}


def test_unopposed_district_is_absent_and_parses_as_no_votes():
    # FL-20 was unopposed in 2024, so the extract has no USR rows for it.
    snap = fl.parse(TEXT, "USR:020", CandidateMap({"Cherfilus-McCormick, Sheila": "D"}), "h20")
    assert snap.cells == []
    assert snap.unit_reporting == {}


def test_district_filter_ignores_other_race_codes():
    # The Senate fixture has no USR rows; a district filter there finds nothing.
    text = fl.load_archive(FIX, "2024-11-05")
    snap = fl.parse(text, "USR:022", CandidateMap({"x, y": "R"}), "h22")
    assert snap.cells == []


def test_juris1num_padding_does_not_matter():
    cmap = CandidateMap({"Franzese, Dan": "R", "Frankel, Lois": "D"})
    padded = fl.parse(TEXT, "USR:022", cmap, "a")
    bare = fl.parse(TEXT, "USR:22", CandidateMap({"Franzese, Dan": "R", "Frankel, Lois": "D"}), "b")
    assert [c.votes for c in padded.cells] == [c.votes for c in bare.cells]
    assert padded.cells[0].votes == {"R": 165248, "D": 201608}


@pytest.mark.parametrize("district", range(1, 29))
def test_every_district_row_lands_in_exactly_one_contest(district):
    rows = [line.split("\t") for line in TEXT.splitlines()[1:]]
    expected = sum(int(r[14]) for r in rows if int(r[7]) == district)
    snap = fl.parse(TEXT, f"USR:{district:03d}", CandidateMap({}), "h")
    assert sum(sum(c.votes.values()) for c in snap.cells) == expected
