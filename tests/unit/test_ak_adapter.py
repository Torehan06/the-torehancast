import csv
import io
from collections import Counter
from pathlib import Path

import pytest
import yaml

from torehancast.adapters import ak_doe as ak
from torehancast.candidates import CandidateMap
from torehancast.elections import CONFIG
from torehancast.http import EXTRA_CAS, ssl_context

FIX = Path(__file__).parents[1] / "fixtures" / "ak"
SENATE = "U.S. Senator"
VOTE_COLUMNS = {"Election Day": "election_day", "Absentee": "mail", "Early Voting": "early", "Question": "provisional"}


def _csv_rows(contest: str = SENATE) -> list[dict]:
    text = ak.load_archive(FIX, "26PRIM")
    return [r for r in csv.DictReader(io.StringIO(text)) if r["Contest_title"] == contest]


@pytest.mark.parametrize(
    "name, expected",
    [
        ("01-600 Ketchikan No. 1", ("1", None)),
        ("38-824 Kipnuk", ("38", None)),
        ("07 010 K Beach", ("7", None)),  # 2022 primary's malformed precinct ID
        ("District 38 - Absentee", ("38", "mail")),
        ("District 1 - Early Voting", ("1", "early")),
        ("District 40  - Question", ("40", "provisional")),  # two spaces, as published
        ("HD99 Fed Overseas Absentee", ("99", "mail")),
    ],
)
def test_locates_precincts_and_pooled_pseudo_precincts(name, expected):
    assert ak.locate(name) == expected


@pytest.mark.parametrize("name", ["Total", "District 1 - Mail", "Anchorage", ""])
def test_unknown_precinct_names_raise(name):
    with pytest.raises(ak.UnknownPrecinct):
        ak.locate(name)


def test_the_two_dan_sullivans_stay_separate():
    cmap = CandidateMap({"Sullivan, Dan S.": "R", "Peltola, Mary": "D"})
    snap = ak.parse(ak.load_archive(FIX, "26PRIM"), SENATE, cmap, "2026_prim_sen")

    by_name = Counter()
    for r in _csv_rows():
        by_name[r["candidate_name"]] += int(r["total_votes"])
    assert by_name["Sullivan, Dan S."] > 0 and by_name["Sullivan, Daniel J. Jr."] > 0
    assert snap.totals()["R"] == by_name["Sullivan, Dan S."]
    assert "Sullivan, Daniel J. Jr." in cmap.unmatched
    assert any("Sullivan, Daniel J. Jr." in w for w in snap.warnings)

    # And the live baseline config never maps the second one to a side.
    spec = yaml.safe_load((CONFIG / "elections.yaml").read_text())["AK"]["2026_prim_sen"]
    assert spec["candidates"]["Sullivan, Dan S."] == "R"
    assert "Sullivan, Daniel J. Jr." not in spec["candidates"]


def test_csv_vote_type_columns_units_and_contest_filter():
    rows = _csv_rows()
    snap = ak.parse(ak.load_archive(FIX, "26PRIM"), SENATE, CandidateMap({}), "2026_prim_sen")

    assert snap.state == "AK"
    assert snap.units() == {"1", "38", "99"}
    expected = Counter()
    for r in rows:
        for label, vt in VOTE_COLUMNS.items():
            expected[vt] += int(r[f"{label}_votes"])
    got = Counter()
    for c in snap.cells:
        got[c.vote_type] += c.total
    assert got == +expected
    assert sum(got.values()) == sum(int(r["total_votes"]) for r in rows)
    # Overseas absentee is all mail; pooled pseudo-precincts never carry Election Day.
    assert {c.vote_type for c in snap.cells if c.unit_id == "99"} == {"mail"}

    governor = ak.parse(ak.load_archive(FIX, "26PRIM"), "Governor / Lieutenant Governor", CandidateMap({}), "gov")
    assert governor.units() == {"1"}
    assert ak.parse(ak.load_archive(FIX, "26PRIM"), "No Such Contest", CandidateMap({}), "x").cells == []


def test_district_reporting_counts_polling_place_precincts_only():
    snap = ak.parse(ak.load_archive(FIX, "26PRIM"), SENATE, CandidateMap({}), "2026_prim_sen")
    assert set(snap.unit_reporting) == {"1", "38"}  # "99" has no polling places
    assert snap.unit_reporting["1"] == 1.0


def test_certified_file_reports_every_district_complete():
    # Kipnuk and Kwigillingok (District 38) recorded no ballots at their own
    # precincts in the Aug 2026 primary, yet the file is final.
    snap = ak.parse(ak.load_archive(FIX, "26PRIM"), SENATE, CandidateMap({}), "2026_prim_sen")
    assert snap.unit_reporting["38"] == 1.0


def _p(ballots, registered):
    return {"ballots": ballots, "votes": ballots, "registered": registered}


def test_district_reporting_weights_by_registration_and_never_writes_off_big_precincts():
    got = ak.district_reporting(
        {
            "1": [_p(0, 500), _p(0, 500)],  # nothing in yet
            "2": [_p(300, 900), _p(0, 100)],  # 10% of registration still out
            "3": [_p(300, 960), _p(0, 40)],  # only a 4% village at zero: done
            "4": [_p(100, 100), _p(0, 900)],  # the big precinct is late: 10%, not 50%
        }
    )
    assert got == {"1": 0.0, "2": pytest.approx(0.9), "3": 1.0, "4": pytest.approx(0.1)}


def test_2022_report_matches_its_total_row_and_strips_party_suffixes():
    text = ak.load_archive(FIX, "22GENR")
    cmap = CandidateMap({"Palin, Sarah": "R", "Begich, Nick": "R", "Peltola, Mary S.": "D"})
    snap = ak.parse(text, "U.S. Representative", cmap, "2022_gen_house")

    total_row = next(l for l in text.splitlines() if l.startswith("Total\t")).split("\t")
    begich, bye, palin, peltola, write_in = (int(x) for x in total_row[1:6])
    assert snap.totals() == {"R": begich + palin, "D": peltola, "other": bye + write_in}
    assert cmap.unmatched == {"Bye, Chris", "Write-in"}
    assert len(snap.units()) == 41  # 40 districts + overseas
    assert {c.vote_type for c in snap.cells} == {"election_day", "mail", "early", "provisional"}


def test_2022_report_rejects_rows_that_disagree_with_the_total():
    text = ak.load_archive(FIX, "22GENR")
    tampered = text.replace("01-600 Ketchikan No. 1\t101\t", "01-600 Ketchikan No. 1\t102\t", 1)
    assert tampered != text
    with pytest.raises(ValueError, match="Total"):
        ak.parse(tampered, "U.S. Representative", CandidateMap({}), "2022_gen_house")


def test_tls_context_keeps_verification_and_adds_the_alaska_intermediate():
    import ssl

    ctx = ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert any(p.name == "globalsign-gcc-r46-ov-tls-ca-2025.pem" for p in EXTRA_CAS)
    subjects = [dict(x[0] for x in c["subject"]).get("commonName") for c in ctx.get_ca_certs()]
    assert "GlobalSign GCC R46 OV TLS CA 2025" in subjects
    assert "GlobalSign Root R46" in subjects  # the intermediate's issuer is a real root
