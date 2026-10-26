"""The precinct crosswalk that rebuilds past Florida results on the 2026 lines.

Synthetic files in the DOS precinct layout; the real-file checks live with the
baselines (tests/unit/test_fl_house.py).
"""

import io
import zipfile

import pytest

from torehancast.adapters import fl_precinct as fp
from torehancast.candidates import CandidateMap

PRES = "President of the United States"
HOUSE = fp.HOUSE_CONTEST


def row(county, precinct, registered, contest, district, candidate, votes, name=None):
    fields = [county, name or county.title(), "1", "11/05/2024", "General", precinct, "Hall",
              str(registered), "0", "0", "0", contest, district, "X", candidate, "REP", "", "", str(votes)]
    return "\t".join(fields)


def text(*rows):
    return "\n".join(rows) + "\n"


# 2026: county AAA has precincts 1-3 in district 9 and 4 in district 10; BBB is all
# district 10; CCC had no House primary anywhere (district 0, but listed via Governor).
PRIMARY = fp.assignment(fp.read_precinct_text(text(
    row("AAA", "0001", 1000, HOUSE, "9", "Smith", 50),
    row("AAA", "0002", 1000, HOUSE, "9", "Smith", 50),
    row("AAA", "3", 1000, HOUSE, "9", "Smith", 50),
    row("AAA", "4", 1000, HOUSE, "10", "Jones", 50),
    row("BBB", "1", 500, HOUSE, "10", "Jones", 50),
    row("CCC", "1", 800, "Governor", "", "Doe", 80),
)))


def year_rows(override=None):
    base = {("AAA", "1"): (1000, 300, 200), ("AAA", "2"): (1000, 250, 250), ("AAA", "3"): (1000, 100, 400),
            ("AAA", "4"): (1000, 500, 100), ("BBB", "1"): (500, 200, 100)}
    base.update(override or {})
    rows = []
    for (county, pct), (reg, r, d) in base.items():
        rows.append(row(county, pct, reg, PRES, "", "Trump", r))
        rows.append(row(county, pct, reg, PRES, "", "Harris", d))
    return fp.read_precinct_text(text(*rows))


CMAP = {"Trump": "R", "Harris": "D"}
NAMES = {"AAA": "ALPHA", "BBB": "BRAVO", "CCC": "CHARLIE"}


def snapshot(year, district=9):
    return fp.district_snapshot(year, PRIMARY, district, PRES, CandidateMap(CMAP), NAMES, "t")


def test_precinct_ids_ignore_leading_zeros_but_keep_suffixes():
    assert fp.norm_precinct(" 0101 ") == "101"
    assert fp.norm_precinct("0101A") == "101A"
    assert fp.norm_precinct("0") == "0"
    assert fp.norm_precinct("pct 7") == "PCT 7"


def test_assignment_reads_districts_and_marks_no_primary_as_zero():
    got = {(r.county_code, r.precinct): r.district for r in PRIMARY.itertuples()}
    assert got == {("AAA", "1"): 9, ("AAA", "2"): 9, ("AAA", "3"): 9, ("AAA", "4"): 10,
                   ("BBB", "1"): 10, ("CCC", "1"): 0}


def test_split_2026_precinct_raises():
    with pytest.raises(fp.CrosswalkError, match="two districts"):
        fp.assignment(fp.read_precinct_text(text(
            row("AAA", "1", 10, HOUSE, "9", "Smith", 1),
            row("AAA", "1", 10, HOUSE, "District 10", "Jones", 1),
        )))


def test_district_is_the_sum_of_its_precincts_per_county_part():
    snap = snapshot(year_rows())
    assert [(c.unit_id, c.votes) for c in snap.cells] == [("ALPHA", {"R": 650, "D": 850})]
    other = snapshot(year_rows(), district=10)
    assert {c.unit_id: c.votes for c in other.cells} == {"ALPHA": {"R": 500, "D": 100}, "BRAVO": {"R": 200, "D": 100}}


def test_unmatched_precinct_over_the_limit_fails_with_a_county_report():
    year = year_rows({("AAA", "1"): (1000, 0, 0), ("AAA", "99"): (1000, 300, 200)})
    with pytest.raises(fp.CrosswalkError) as err:
        snapshot(year)
    assert "AAA: 23.81% unmatched (500 no 2026 precinct, 0 boundary moved, of 2,100)" in str(err.value)


def test_registration_jump_counts_as_a_moved_boundary():
    # Same ID, but twice the voters: a different patch of ground.
    year = year_rows({("AAA", "3"): (2000, 100, 400)})
    with pytest.raises(fp.CrosswalkError, match="AAA: .* 500 boundary moved"):
        snapshot(year)


def test_countywide_registration_change_is_not_a_boundary_change():
    year = year_rows({k: (reg * 13 // 10, r, d) for k, (reg, r, d) in {
        ("AAA", "1"): (1000, 300, 200), ("AAA", "2"): (1000, 250, 250),
        ("AAA", "3"): (1000, 100, 400), ("AAA", "4"): (1000, 500, 100)}.items()})
    assert snapshot(year).cells[0].votes == {"R": 650, "D": 850}


def test_small_unmatched_share_is_spread_so_county_totals_stay_exact():
    # 0.5% of AAA's vote is in a precinct that no longer exists.
    big = {("AAA", p): (1000, 10000, 10000) for p in ("1", "2", "3", "4")}
    big[("AAA", "77")] = (1000, 100, 100)
    year = year_rows(big)
    nine = snapshot(year).cells[0].votes
    ten = {c.unit_id: c.votes for c in snapshot(year, 10).cells}["ALPHA"]
    assert nine["R"] + ten["R"] == 40100
    assert nine == {"R": 30075, "D": 30075}


def test_counties_outside_the_district_do_not_block_it():
    # BBB is all district 10; a broken join there doesn't touch district 9.
    year = year_rows({("BBB", "1"): (500, 0, 0), ("BBB", "50"): (500, 200, 100)})
    assert snapshot(year).cells[0].votes == {"R": 650, "D": 850}
    with pytest.raises(fp.CrosswalkError, match="BBB"):
        snapshot(year, 10)


def test_wrong_field_count_is_refused():
    with pytest.raises(ValueError, match="expected 19 fields"):
        fp.read_precinct_text("a\tb\tc\n")


def test_zip_archive_reads_every_county_file(tmp_path):
    path = tmp_path / "pct.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("AAA_PctResults.txt", text(row("AAA", "1", 10, PRES, "", "Trump", 3)))
        z.writestr("BBB_PctResults.txt", text(row("BBB", "1", 10, PRES, "", "Trump", 4)))
        z.writestr("readme.pdf", b"%PDF")
    df = fp.read_precinct_archive(path)
    assert sorted(df.county_code) == ["AAA", "BBB"]
    assert df.votes.sum() == 7


def test_district_numbers_parse_from_common_spellings():
    assert fp.district_number("22") == 22
    assert fp.district_number("022") == 22
    assert fp.district_number("District 22") == 22
    with pytest.raises(ValueError):
        fp.district_number("")


def test_archive_only_adapter_refuses_live_use():
    with pytest.raises(NotImplementedError):
        fp.fetch_source(None, None)
    with pytest.raises(NotImplementedError):
        fp.parse("", "", None, "")


def test_county_names_come_from_the_extract():
    extract = "CountyCode\tCountyName\nDAD\tMiami-Dade\nPAL\tPalm Beach\n"
    assert fp.county_names(extract) == {"DAD": "MIAMI-DADE", "PAL": "PALM BEACH"}


def test_county_totals_need_no_crosswalk():
    snap = fp.county_snapshot(year_rows(), PRES, CandidateMap(CMAP), NAMES, "2016_pres")
    assert {c.unit_id: c.votes for c in snap.cells} == {"ALPHA": {"R": 1150, "D": 950}, "BRAVO": {"R": 200, "D": 100}}


def test_fips_table_spells_every_county_as_the_live_extract_does():
    names = fp.county_names(fl_extract_text())
    assert sorted(fp.FIPS.values()) == sorted(names.values())


def fl_extract_text():
    from pathlib import Path
    return (Path(__file__).parents[1] / "fixtures" / "fl" / "extract_20241105.txt").read_text(encoding="latin-1")


def test_plan_counties_read_the_block_assignment_file():
    blocks = "120570101011000,14\n120990001001000,22\n120110001001000,22\n120860001001000,27\n"
    assert fp.plan_counties(blocks, 22) == {"PALM BEACH", "BROWARD"}
    assert fp.plan_counties(blocks, 27) == {"MIAMI-DADE"}


def test_crosswalk_counties_must_match_the_plan():
    snap = snapshot(year_rows())  # district 9 → ALPHA only
    fp.FIPS.setdefault("990", "ALPHA")
    try:
        fp.check_against_plan(snap, "129900001001000,9\n", 9)
        with pytest.raises(fp.CrosswalkError, match="enacted plan"):
            fp.check_against_plan(snap, "129900001001000,9\n120110001001000,9\n", 9)
    finally:
        del fp.FIPS["990"]
