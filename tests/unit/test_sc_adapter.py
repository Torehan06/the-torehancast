import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from torehancast.adapters import sc_clarity as sc
from torehancast.candidates import CandidateMap

FIX = Path(__file__).parents[1] / "fixtures" / "sc"


def test_parses_all_46_counties_vote_types_and_matches_choice_totals():
    text = sc.load_archive(FIX, "122436")
    cmap = CandidateMap({"REP Donald J Trump/JD Vance": "R", "DEM Kamala D Harris/Tim Walz": "D"})
    snap = sc.parse(text, "President and Vice President", cmap, "2024_pres")

    assert snap.state == "SC"
    assert snap.race == "2024_pres"
    assert snap.as_of == "7/30/2025 10:46:52 AM EDT"
    assert len(snap.units()) == 46
    assert {c.vote_type for c in snap.cells} == {"early", "mail", "election_day", "provisional"}
    assert len(snap.unit_reporting) == 46
    assert all(v == 1.0 for v in snap.unit_reporting.values())

    totals = snap.totals()
    assert totals["R"] == 1_483_747
    assert totals["D"] == 1_028_452
    assert cmap.unmatched == {
        "CON Randall A Terry/Stephen E Broden",
        "GRN Jill Stein/Rudolph Butch Ware",
        "LIB Chase Oliver/Mike ter Maat",
        "UNC Cornel West/Melina Abdulla",
        "WRK Claudia De La Cruz/Karina Garcia",
    }

    # Verify provisional cells sum Provisional + Failsafe + Failsafe Provisional per county.
    root = ET.fromstring(text)
    contest = next(c for c in root.findall("Contest") if c.attrib.get("text") == "President and Vice President")
    trump = next(ch for ch in contest.findall("Choice") if ch.attrib["text"] == "REP Donald J Trump/JD Vance")
    raw_prov = sum(
        int(c.attrib["votes"])
        for vt in trump.findall("VoteType")
        if vt.attrib["name"] in ("Provisional", "Failsafe", "Failsafe Provisional")
        for c in vt.findall("County")
        if c.attrib["name"] == "Charleston"
    )
    charleston_prov = next(c for c in snap.cells if c.unit_id == "CHARLESTON" and c.vote_type == "provisional")
    assert charleston_prov.votes["R"] == raw_prov


def test_parses_2020_in_person_absentee_and_2024_provionsal_typo():
    text_2020 = sc.load_archive(FIX, "106502")
    cmap_2020 = CandidateMap(
        {"REP Donald J Trump | Michael R Pence": "R", "DEM Joseph R Biden | Kamala D Harris": "D"}
    )
    snap_2020 = sc.parse(text_2020, "President and Vice President", cmap_2020, "2020_pres")
    assert {c.vote_type for c in snap_2020.cells} == {"early", "mail", "election_day", "provisional"}
    totals_2020 = snap_2020.totals()
    assert totals_2020["R"] == 1_385_103
    assert totals_2020["D"] == 1_091_541

    # State Senate District 20 in 2024 has the real "Provionsal" typo in Clarity's XML.
    text_2024 = sc.load_archive(FIX, "122436")
    cmap_sd20 = CandidateMap({"REP Benjamin Dunn": "R", "DEM Ed Sutton": "D"})
    snap_sd20 = sc.parse(text_2024, "State  Senate, District  20", cmap_sd20, "2024_sd20")
    assert snap_sd20.units() == {"CHARLESTON"}
    assert {c.vote_type for c in snap_sd20.cells} == {"early", "mail", "election_day", "provisional"}


def test_partial_precinct_reporting_and_missing_contest():
    text = sc.load_archive(FIX, "122436")
    root = ET.fromstring(text)
    abbeville = next(
        c for c in root.findall("./ElectionVoterTurnout/Counties/County") if c.attrib["name"] == "Abbeville"
    )
    abbeville.set("precinctsReported", "9")
    abbeville.set("precinctsParticipating", "15")
    modified_xml = ET.tostring(root, encoding="unicode")

    cmap = CandidateMap({"REP Donald J Trump/JD Vance": "R", "DEM Kamala D Harris/Tim Walz": "D"})
    snap = sc.parse(modified_xml, "President and Vice President", cmap, "2024_pres")
    assert snap.unit_reporting["ABBEVILLE"] == pytest.approx(9 / 15)

    missing = sc.parse(text, "Nonexistent Contest", CandidateMap({}), "none")
    assert missing.cells == []
    assert missing.unit_reporting == {}


def test_urls_and_read_zip():
    assert sc.version_url("122436") == "https://www.enr-scvotes.org/SC/122436/current_ver.txt"
    assert (
        sc.results_url("122436", "359624")
        == "https://www.enr-scvotes.org/SC/122436/359624/reports/detailxml.zip"
    )
    raw = sc.load_archive(FIX, "122436")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("detail.xml", raw.encode("utf-8"))
    extracted = sc.read_zip(buf.getvalue())
    cmap = CandidateMap({"REP Donald J Trump/JD Vance": "R", "DEM Kamala D Harris/Tim Walz": "D"})
    assert sc.parse(extracted, "President and Vice President", cmap, "2024_pres").totals() == {
        "R": 1_483_747,
        "D": 1_028_452,
        "other": 35_941,
    }
