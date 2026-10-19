import csv
import io
from pathlib import Path

import pandas as pd
import pytest

from torehancast.adapters import mn_sos as mn
from torehancast.candidates import CandidateMap
from torehancast.elections import ROOT

FIX = Path(__file__).parents[1] / "fixtures" / "mn"


def test_county_table_matches_built_in_lookup_and_demographics():
    raw_table = (FIX / "Cntytbl_20241105.txt").read_text(encoding="utf-8-sig")
    parsed = mn.parse_counties(raw_table)
    assert len(parsed) == 87
    assert parsed == mn.COUNTIES

    demo = pd.read_csv(ROOT / "data" / "demographics" / "MN.csv")
    assert set(parsed.values()) == set(demo["unit_id"])
    assert parsed["69"] == "ST. LOUIS"
    assert parsed["37"] == "LAC QUI PARLE"
    assert parsed["39"] == "LAKE OF THE WOODS"
    assert parsed["43"] == "MCLEOD"


def test_parses_all_87_counties_and_matches_column_15_county_totals():
    text = mn.load_archive(FIX, "2024-11-05")
    cmap = CandidateMap(
        {"Donald J. Trump and JD Vance": "R", "Kamala D. Harris and Tim Walz": "D"}
    )
    snap = mn.parse(text, "U.S. President & Vice President", cmap, "2024_pres")

    assert snap.state == "MN"
    assert snap.race == "2024_pres"
    assert len(snap.cells) == 87
    assert {c.vote_type for c in snap.cells} == {"all"}
    assert len(snap.unit_reporting) == 87
    assert all(v == 1.0 for v in snap.unit_reporting.values())

    totals = snap.totals()
    assert totals["D"] == 1_656_979
    assert totals["R"] == 1_519_032
    assert "Robert F. Kennedy Jr. and Nicole Shanahan" in cmap.unmatched
    assert "WRITE-IN" in cmap.unmatched

    # Column 15 in the MN SOS file is the total votes cast in the contest for that county.
    expected_county_total: dict[str, int] = {}
    for row in csv.reader(io.StringIO(text), delimiter=";"):
        if len(row) >= 16:
            expected_county_total[mn.COUNTIES[row[1].zfill(2)]] = int(row[15])
    for cell in snap.cells:
        assert cell.total == expected_county_total[cell.unit_id]


def test_multi_contest_filtering_bom_and_office_id_matching():
    pres = (FIX / "USPresCty_20241105.txt").read_text(encoding="utf-8-sig")
    sen = (FIX / "ussenatecty_20241105.txt").read_text(encoding="utf-8-sig")
    combined_with_bom = "\ufeff" + pres + "\n" + sen

    cmap = CandidateMap({"Royce White": "R", "Amy Klobuchar": "D"})
    by_name = mn.parse(combined_with_bom, "U.S. Senator", cmap, "2024_sen")
    by_code = mn.parse(combined_with_bom, "0102", CandidateMap({"Royce White": "R", "Amy Klobuchar": "D"}), "2024_sen")

    assert len(by_name.cells) == 87
    assert by_name.totals() == {"D": 1_792_441, "R": 1_291_712, "other": 105_170}
    assert by_code.totals() == by_name.totals()


def test_partial_precinct_reporting_and_missing_contest():
    lines = (FIX / "ussenatecty_20241105.txt").read_text(encoding="utf-8-sig").splitlines()
    modified = []
    for line in lines:
        parts = line.split(";")
        if parts[1] == "01":  # Aitkin County (51 precincts)
            parts[11] = "17"
            parts[12] = "51"
        modified.append(";".join(parts))

    cmap = CandidateMap({"Royce White": "R", "Amy Klobuchar": "D"})
    snap = mn.parse("\n".join(modified), "U.S. Senator", cmap, "2024_sen")
    assert snap.unit_reporting["AITKIN"] == pytest.approx(17 / 51)

    missing = mn.parse("\n".join(modified), "U.S. Representative District 1", CandidateMap({}), "none")
    assert missing.cells == []
    assert missing.unit_reporting == {}


def test_urls():
    assert (
        mn.results_url("2024-11-05")
        == "https://electionresultsfiles.sos.mn.gov/20241105/ussenatecty.txt"
    )
    assert (
        mn.results_url("2024-11-05", "USPresCty.txt")
        == "https://electionresultsfiles.sos.mn.gov/20241105/USPresCty.txt"
    )
    assert (
        mn.county_table_url("2024-11-05")
        == "https://electionresultsfiles.sos.mn.gov/20241105/Cntytbl.txt"
    )
