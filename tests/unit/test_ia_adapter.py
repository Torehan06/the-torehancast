import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from torehancast.adapters import ia_clarity as ia
from torehancast.candidates import CandidateMap
from torehancast.elections import ROOT

FIX = Path(__file__).parents[1] / "fixtures" / "ia"


def test_parses_all_99_counties_vote_types_and_matches_choice_totals():
    text = ia.load_archive(FIX, "122322")
    cmap = CandidateMap(
        {"Donald J. Trump and JD Vance": "R", "Kamala D. Harris and Tim Walz": "D"}
    )
    snap = ia.parse(text, "President and Vice President", cmap, "2024_pres")

    assert snap.state == "IA"
    assert snap.race == "2024_pres"
    assert snap.as_of == "12/16/2024 8:19:40 AM CST"
    assert len(snap.units()) == 99
    assert "O'BRIEN" in snap.units()
    assert {c.vote_type for c in snap.cells} == {"early", "election_day"}
    assert len(snap.unit_reporting) == 99
    assert all(v == 1.0 for v in snap.unit_reporting.values())

    demo = pd.read_csv(ROOT / "data" / "demographics" / "IA.csv")
    assert snap.units() == set(demo["unit_id"])

    totals = snap.totals()
    assert totals["R"] == 927_019
    assert totals["D"] == 707_278
    assert totals["other"] == 29_209
    assert "Robert F. Kennedy Jr and Nicole Shanahan" in cmap.unmatched
    assert "Write-in" in cmap.unmatched


def test_parses_2020_us_senate_contest():
    text = ia.load_archive(FIX, "106279")
    cmap = CandidateMap({"Joni Ernst": "R", "Theresa Greenfield": "D"})
    snap = ia.parse(text, "United States Senator", cmap, "2020_sen")

    assert len(snap.units()) == 99
    assert {c.vote_type for c in snap.cells} == {"early", "election_day"}
    assert snap.totals() == {"R": 864_997, "D": 754_859, "other": 51_972}
    assert cmap.unmatched == {"Rick Stewart", "Suzanne Herzog", "Write-in"}


def test_partial_precinct_reporting_and_missing_contest():
    text = ia.load_archive(FIX, "122322")
    root = ET.fromstring(text)
    polk = next(
        c for c in root.findall("./ElectionVoterTurnout/Counties/County") if c.attrib["name"] == "Polk"
    )
    polk.set("precinctsReported", "88")
    polk.set("precinctsParticipating", "176")
    modified_xml = ET.tostring(root, encoding="unicode")

    cmap = CandidateMap(
        {"Donald J. Trump and JD Vance": "R", "Kamala D. Harris and Tim Walz": "D"}
    )
    snap = ia.parse(modified_xml, "President and Vice President", cmap, "2024_pres")
    assert snap.unit_reporting["POLK"] == pytest.approx(88 / 176)

    missing = ia.parse(text, "Governor and Lieutenant Governor", CandidateMap({}), "none")
    assert missing.cells == []
    assert missing.unit_reporting == {}


def test_urls_and_read_zip():
    assert ia.version_url("122322") == "https://electionresults.iowa.gov/IA/122322/current_ver.txt"
    assert (
        ia.results_url("122322", "356043")
        == "https://electionresults.iowa.gov/IA/122322/356043/reports/detailxml.zip"
    )
    raw = ia.load_archive(FIX, "122322")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("detail.xml", raw.encode("utf-8"))
    extracted = ia.read_zip(buf.getvalue())
    cmap = CandidateMap(
        {"Donald J. Trump and JD Vance": "R", "Kamala D. Harris and Tim Walz": "D"}
    )
    assert ia.parse(extracted, "President and Vice President", cmap, "2024_pres").totals() == {
        "R": 927_019,
        "D": 707_278,
        "other": 29_209,
    }
