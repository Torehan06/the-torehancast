import csv
import io
import zipfile
from pathlib import Path

import pytest

from torehancast.adapters import nc_sbe as nc
from torehancast.candidates import CandidateMap

FIX = Path(__file__).parents[1] / "fixtures" / "nc"


def test_parses_precinct_rows_and_legacy_one_stop_column():
    text = nc.load_archive(FIX, "2020-11-03")
    cmap = CandidateMap({"Donald J. Trump": "R", "Joseph R. Biden": "D"})
    snap = nc.parse(text, "US PRESIDENT", cmap, "2020_pres")

    assert snap.state == "NC"
    assert snap.race == "2020_pres"
    assert {c.unit_id for c in snap.cells} == {"DARE", "TYRRELL"}
    # 2020 used "One Stop" for early voting; canonical_vote_type maps it to "early".
    assert {c.vote_type for c in snap.cells} == {"early", "mail", "election_day", "provisional"}
    assert cmap.unmatched == {
        "Don Blankenship",
        "Howie Hawkins",
        "Jo Jorgensen",
        "Write-In (Miscellaneous)",
    }
    # Administrative/absentee precincts have 0 Election Day votes, so reporting is the
    # share of precincts in the county with positive Election Day votes.
    assert snap.unit_reporting["DARE"] == pytest.approx(16 / 22)
    assert snap.unit_reporting["TYRRELL"] == pytest.approx(6 / 10)


def test_county_totals_match_the_files_total_votes_column():
    text = nc.load_archive(FIX, "2024-11-05")
    cmap = CandidateMap({"Donald J. Trump": "R", "Kamala D. Harris": "D"})
    snap = nc.parse(text, "US PRESIDENT", cmap, "2024_pres")

    expected = {"DARE": {"R": 0, "D": 0}, "TYRRELL": {"R": 0, "D": 0}}
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        if row["Contest Name"] != "US PRESIDENT":
            continue
        county = row["County"].strip().upper()
        if row["Choice"] == "Donald J. Trump":
            expected[county]["R"] += int(row["Total Votes"])
        elif row["Choice"] == "Kamala D. Harris":
            expected[county]["D"] += int(row["Total Votes"])

    for county in ("DARE", "TYRRELL"):
        county_cells = [c for c in snap.cells if c.unit_id == county]
        assert sum(c.votes["R"] for c in county_cells) == expected[county]["R"]
        assert sum(c.votes["D"] for c in county_cells) == expected[county]["D"]


def test_missing_contest_yields_no_cells():
    text = nc.load_archive(FIX, "2024-11-05")
    snap = nc.parse(text, "US SENATE (SPECIAL)", CandidateMap({}), "2024_sen")
    assert snap.cells == []
    assert snap.unit_reporting == {}


def test_results_url_and_read_zip():
    assert (
        nc.results_url("2024-11-05")
        == "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2024_11_05/results_pct_20241105.zip"
    )
    raw = nc.load_archive(FIX, "2024-11-05")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("results_pct_20241105.txt", raw.encode("utf-8"))
    extracted = nc.read_zip(buf.getvalue())
    cmap = CandidateMap({"Donald J. Trump": "R", "Kamala D. Harris": "D"})
    assert nc.parse(extracted, "US PRESIDENT", cmap, "2024_pres").totals() == (
        nc.parse(raw, "US PRESIDENT", CandidateMap({"Donald J. Trump": "R", "Kamala D. Harris": "D"}), "2024_pres").totals()
    )
