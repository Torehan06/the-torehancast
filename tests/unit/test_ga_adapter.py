import json
from pathlib import Path

from torehancast.adapters import ga_enhanced_voting as ga
from torehancast.candidates import CandidateMap

FIX = Path(__file__).parents[1] / "fixtures" / "ga"


def load(name):
    return json.loads((FIX / name).read_text())


def test_parses_county_with_vote_types():
    doc = load("2022NovGen_appling-county-ga.json")
    cmap = CandidateMap({"Herschel Junior Walker (Rep)": "R", "Raphael Warnock (I) (Dem)": "D"})
    cells, reporting = ga.parse_county(doc, "US Senate", cmap)

    assert {c.unit_id for c in cells} == {"APPLING"}
    assert {c.vote_type for c in cells} == {"early", "mail", "election_day", "provisional"}
    # Pre-2024 archives were migrated from Clarity without precinct status (totalUnits = 0).
    assert reporting is None
    # Chase Oliver (Lib) is not configured, so his votes land in "other".
    assert all("other" in c.votes for c in cells)
    assert cmap.unmatched == {"Chase Oliver (Lib)"}


def test_county_totals_match_the_documents_own_totals():
    doc = load("2024NovGen_fulton-county-ga.json")
    cmap = CandidateMap({"Donald J. Trump (Rep)": "R", "Kamala D. Harris (Dem)": "D"})
    cells, _ = ga.parse_county(doc, "President of the US", cmap)

    options = doc["ballotItems"][0]["summaryResults"]["ballotOptions"]
    expected = {o["name"][0]["text"]: o["voteCount"] for o in options}
    assert sum(c.votes["R"] for c in cells) == expected["Donald J. Trump (Rep)"]
    assert sum(c.votes["D"] for c in cells) == expected["Kamala D. Harris (Dem)"]


def test_missing_contest_yields_no_cells():
    doc = load("2022NovGen_appling-county-ga.json")
    cells, reporting = ga.parse_county(doc, "US Senate (Special)", CandidateMap({}))
    assert cells == [] and reporting is None


def test_unit_id_is_stable():
    assert ga.unit_id("Appling County") == "APPLING"
    assert ga.unit_id("DeKalb County") == "DEKALB"
