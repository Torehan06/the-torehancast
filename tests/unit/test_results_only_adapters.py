"""W4a: every parsed feed reads all its results-only contests in one pass.

Fixtures are cut from the archived 2024 official files (House contests only, plus a
few rows of other races to prove filtering). Expected numbers were added up from the
fixtures independently (awk over the rows / XML attributes), not by these parsers.
"""

import json
from pathlib import Path

import pytest

from torehancast import public_json, publish, results_only
from torehancast.adapters import clarity, fl_dos, ga_enhanced_voting as ga, ia_clarity, mn_sos, nc_sbe, sc_clarity
from torehancast.config import ResultsContest
from torehancast.results_only import Choice, ContestTotals

FIXTURES = Path(__file__).parents[1] / "fixtures"


def contest(st, n, template, sides=None):
    return ResultsContest(f"2026-{st}-H{n:02d}", "house", n, f"{st}/x", template.format(n=n), sides or {})


# -- side keys ---------------------------------------------------------------------------

def test_keys_follow_party_labels_with_d_and_r_first_and_other_last():
    t = results_only.totals([
        Choice("Green Person", "GRN", 5), Choice("Rep Person", "REP", 40),
        Choice("Write-In", "NON", 2), Choice("Dem Person", "Dem", 50), Choice("Mystery", None, 3),
    ], {}, 0.5, "T")
    assert list(t.candidates) == ["D", "R", "G", "other"]
    assert t.candidates == {"D": "Dem Person", "R": "Rep Person", "G": "Green Person", "other": "Other candidates"}
    assert t.votes == {"D": 50, "R": 40, "G": 5, "other": 5}
    assert (t.pct_reporting, t.as_of) == (0.5, "T")


def test_keys_never_depend_on_vote_order():
    def keyed(a, b):
        return results_only.totals([Choice("Ann", "DEM", a), Choice("Bea", "DEM", b)], {}, None).candidates
    assert keyed(10, 90) == keyed(90, 10) == {"D": "Ann", "D2": "Bea"}


def test_rows_for_one_name_are_summed_across_counties():
    t = results_only.totals([Choice("Ann", "DEM", 3), Choice("Bob", "REP", 4), Choice("Ann", "DEM", 5)], {}, None)
    assert t.votes == {"D": 8, "R": 4}


def test_config_sides_name_or_pool_candidates():
    sides = {"Indie Star": "I", "Rep Person": "other"}
    t = results_only.totals([Choice("Rep Person", "REP", 1), Choice("Indie Star", "ALN", 9), Choice("Dem", "DEM", 4)],
                            sides, None)
    assert t.candidates == {"I": "Indie Star", "D": "Dem", "other": "Other candidates"}
    assert t.votes == {"I": 9, "D": 4, "other": 1}


def test_at_most_five_named_candidates():
    parties = ["DEM", "REP", "LIB", "GRN", "CON", "IND", "DEM"]
    t = results_only.totals([Choice(f"c{i}", p, 1) for i, p in enumerate(parties)], {}, None)
    assert list(t.candidates) == ["D", "D2", "R", "L", "G", "other"]
    assert t.votes["other"] == 2


@pytest.mark.parametrize("label", ["UNC", "NON", "ALN", "", None])
def test_ambiguous_or_unknown_labels_pool_into_other(label):
    t = results_only.totals([Choice("A", "DEM", 1), Choice("B", label, 1)], {}, None)
    assert t.candidates == {"D": "A", "other": "Other candidates"}


@pytest.mark.parametrize("name", ["Write-In", "WRITE-IN (Miscellaneous)", "Write-ins", "Scattering"])
def test_write_ins_pool_into_other_whatever_their_label(name):
    t = results_only.totals([Choice("A", "DEM", 1), Choice(name, "DEM", 1)], {}, None)
    assert t.candidates == {"D": "A", "other": "Other candidates"}


@pytest.mark.parametrize("votes", [-1, 1.5, True])
def test_malformed_vote_counts_fail_loudly(votes):
    with pytest.raises(ValueError):
        results_only.totals([Choice("A", "DEM", votes)], {}, None)


def test_reporting_fraction_is_none_without_a_total():
    assert results_only.fraction(3, 0) is None
    assert results_only.fraction(3, 4) == 0.75


# -- one pass per feed, on real 2024 rows ------------------------------------------------

def test_nc_reads_district_contests_and_publishes_no_reporting_guess():
    text = (FIXTURES / "nc/house_pct_20241105.txt").read_text()
    contests = [contest("NC", n, "US HOUSE OF REPRESENTATIVES DISTRICT {n:02d}") for n in (2, 3)]
    found = nc_sbe.parse_all_contests(text, contests)
    assert set(found) == {"2026-NC-H02"}  # NC-3 isn't in this file: no votes yet, not an error
    assert found["2026-NC-H02"] == ContestTotals(
        {"D": "Deborah K. Ross", "R": "Alan D. Swain", "G": "Michael Dublin"},
        {"D": 268662, "R": 128164, "G": 8691}, None)


def test_fl_reads_district_rows_by_juris_and_counts_each_county_once():
    text = (FIXTURES / "fl/house_extract_20241105.txt").read_text(encoding="latin-1")
    contests = [contest("FL", n, "USR:{n:03d}") for n in (2, 3, 20)]
    found = fl_dos.parse_all_contests(text, contests)
    assert set(found) == {"2026-FL-H02", "2026-FL-H03"}  # FL-20 was unopposed: absent from the file
    assert found["2026-FL-H02"] == ContestTotals({"D": "Bailey, Yen", "R": "Dunn, Neal"},
                                                 {"D": 154323, "R": 247957}, 1.0)
    assert found["2026-FL-H03"].votes == {"D": 150283, "R": 241174}


def test_fl_district_filter_matches_the_modeled_parser():
    # The same "USR:022" spelling selects the same rows in parse() (W7 FL) and here.
    assert fl_dos.contest_filter("USR:003") == ("USR", 3) and fl_dos.contest_filter("USS") == ("USS", None)


def test_sc_reads_contest_totals_and_its_own_precinct_counts():
    text = (FIXTURES / "sc/house/122436_detail.xml").read_text()
    template = "U.S.  House of Representatives, District  {n}"
    found = sc_clarity.parse_all_contests(text, [contest("SC", n, template) for n in (3, 6, 7)])
    assert set(found) == {"2026-SC-H03", "2026-SC-H06"}
    sc3, sc6 = found["2026-SC-H03"], found["2026-SC-H06"]
    assert sc3.candidates == {"D": "DEM Bryon L Best", "R": "REP Sheri Biggs", "other": "Other candidates"}
    assert sc3.votes == {"D": 87735, "R": 248451, "other": 9918 + 609}  # Alliance + write-in
    assert sc6.votes == {"D": 182056, "R": 112360, "L": 5279, "other": 4927 + 1056 + 299}
    assert sc3.pct_reporting == 1.0 and sc3.as_of == "7/30/2025 10:46:52 AM EDT"


def test_sc_named_minor_candidate_via_config_sides():
    text = (FIXTURES / "sc/house/122436_detail.xml").read_text()
    c = contest("SC", 3, "U.S.  House of Representatives, District  {n}", {"ALN Mike Bedenbaugh": "A"})
    t = sc_clarity.parse_all_contests(text, [c])["2026-SC-H03"]
    assert t.votes == {"A": 9918, "D": 87735, "R": 248451, "other": 609}


def test_ia_and_generic_clarity_share_the_clarity_parser():
    text = (FIXTURES / "ia/122322_detail.xml").read_text()
    c = contest("IA", 1, "United States Representative District {n}")
    assert ia_clarity.parse_all_contests(text, [c]) == clarity.parse_all_contests(text, [c])
    t = ia_clarity.parse_all_contests(text, [c])["2026-IA-H01"]
    assert {"D", "R"} <= t.votes.keys() and t.pct_reporting == 1.0


def test_ga_sums_county_documents_and_their_reporting_units():
    docs = [json.loads(p.read_text()) for p in sorted((FIXTURES / "ga/house").glob("*.json"))]
    template = "US House of Representatives - District {n}"
    found = ga.parse_all_contests(docs, [contest("GA", n, template) for n in (1, 5, 6, 7, 8)])
    assert set(found) == {"2026-GA-H01", "2026-GA-H05", "2026-GA-H06", "2026-GA-H07"}
    assert found["2026-GA-H01"] == ContestTotals(
        {"D": "Patti Hewitt (Dem)", "R": 'Earl L. "Buddy" Carter (I) (Rep)'}, {"D": 1315, "R": 6697},
        1.0, "2025-01-02T19:04:20.416202Z")  # the later of the two documents' asOf
    assert found["2026-GA-H07"].votes == {"D": 87919, "R": 95223}


def test_mn_matches_office_name_maps_dfl_and_counts_each_county_once():
    text = (FIXTURES / "mn/ussenatecty_20241105.txt").read_text(encoding="utf-8-sig")
    c = ResultsContest("2026-MN-SEN", "senate", None, "MN/x", "U.S. Senator", {})
    t = mn_sos.parse_all_contests(text, [c])["2026-MN-SEN"]
    assert t.candidates["D"] == "Amy Klobuchar" and t.candidates["R"] == "Royce White"
    assert sum(t.votes.values()) == sum(
        int(row.split(";")[13]) for row in text.splitlines() if row.split(";")[4:5] == ["U.S. Senator"])
    assert t.pct_reporting == 1.0


def test_unverified_contest_is_never_matched():
    text = (FIXTURES / "nc/house_pct_20241105.txt").read_text()
    unverified = ResultsContest("2026-NC-H02", "house", 2, "NC/x", None, {})
    assert nc_sbe.parse_all_contests(text, [unverified]) == {}


def test_generic_clarity_needs_its_state_root_and_election():
    class Feed:
        url, election_id = None, "123"
    with pytest.raises(ValueError):
        clarity.fetch_source(None, Feed())


# -- through the publisher and the public checker -----------------------------------------

def test_parsed_contests_publish_as_valid_results_only_json(tmp_path):
    docs = [json.loads(p.read_text()) for p in sorted((FIXTURES / "ga/house").glob("*.json"))]
    contests = [contest("GA", n, "US House of Representatives - District {n}") for n in (1, 5, 6, 7, 8)]
    found = ga.parse_all_contests(docs, contests)
    updates = [results_only.update(c, "GA", found.get(c.race_id), "2026-11-03T20:00:00-05:00") for c in contests]
    for u in updates:
        payload = publish.state_summary(u, "replay")
        assert payload["modeled"] is False
        assert payload["status"] == ("waiting" if u.race == "2026-GA-H08" else "live")
    publish.publish(updates, publish.LocalWriter(tmp_path), mode="replay")
    assert [p.name for p in tmp_path.rglob("*.json")] == ["house.json"]
    assert public_json.check_tree(tmp_path, mode="replay").files == 1
