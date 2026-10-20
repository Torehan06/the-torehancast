"""The 2026 federal race list: 435 House seats and 35 Senate races."""

import pytest

from torehancast import districts


def test_apportionment_is_the_2020_census_one():
    assert sum(districts.APPORTIONMENT.values()) == 435
    assert len(districts.APPORTIONMENT) == 50
    assert districts.APPORTIONMENT["CA"] == 52 and districts.APPORTIONMENT["TX"] == 38
    assert {s for s, n in districts.APPORTIONMENT.items() if n == 1} == {"AK", "DE", "ND", "SD", "VT", "WY"}


def test_house_race_ids_are_canonical_and_round_trip():
    ids = districts.house_race_ids()
    assert len(ids) == len(set(ids)) == 435
    assert districts.house_race_id("NC", 1) == "2026-NC-H01"
    assert districts.house_race_id("AK", 1) == "2026-AK-HAL"
    for race_id in ids:
        state, n = districts.parse_house_race_id(race_id)
        assert districts.house_race_id(state, n) == race_id


@pytest.mark.parametrize("race_id", [
    "2026-NC-H15", "2026-NC-H00", "2026-NC-H1", "2026-AK-H01", "2026-NC-HAL", "2026-DC-HAL",
    "2026-NC-SEN", "2024-NC-H01",
])
def test_invalid_house_ids_are_rejected(race_id):
    assert districts.parse_house_race_id(race_id) is None


def test_district_numbers_outside_the_apportionment_raise():
    with pytest.raises(ValueError):
        districts.house_race_id("NC", 15)


def test_senate_races_are_class_2_plus_the_two_specials():
    ids = districts.senate_race_ids()
    assert len(ids) == 35
    assert "2026-FL-SEN-SPECIAL" in ids and "2026-OH-SEN-SPECIAL" in ids
    assert "2026-CA-SEN" not in ids
    with pytest.raises(ValueError):
        districts.senate_race_id("CA")


def test_web_senate_list_matches(tmp_path):
    from pathlib import Path
    import re
    source = (Path(__file__).resolve().parents[2] / "web/src/data/states.ts").read_text()
    class_2 = set(re.findall(r"'([A-Z]{2})'", source.split("const CLASS_2 = [")[1].split("]")[0]))
    specials = set(re.findall(r"'([A-Z]{2})'", source.split("const SPECIALS = [")[1].split("]")[0]))
    assert class_2 == districts.SENATE_CLASS_2
    assert specials == districts.SENATE_SPECIALS
