"""Which federal races exist on Nov 3, 2026, and their canonical race IDs.

House seats use the 2020-census apportionment (435 seats, in force 2022-2030). District
lines may change mid-decade, district counts may not. Senate seats are Class 2 plus the
Florida and Ohio specials. The web app keeps a copy in web/src/data/states.ts.

    house_race_id("NC", 1)  -> "2026-NC-H01"
    house_race_id("AK", 1)  -> "2026-AK-HAL"   (at-large)
"""

from __future__ import annotations

import re

YEAR = 2026

APPORTIONMENT: dict[str, int] = {
    "AL": 7, "AK": 1, "AZ": 9, "AR": 4, "CA": 52, "CO": 8, "CT": 5, "DE": 1, "FL": 28, "GA": 14,
    "HI": 2, "ID": 2, "IL": 17, "IN": 9, "IA": 4, "KS": 4, "KY": 6, "LA": 6, "ME": 2, "MD": 8,
    "MA": 9, "MI": 13, "MN": 8, "MS": 4, "MO": 8, "MT": 2, "NE": 3, "NV": 4, "NH": 2, "NJ": 12,
    "NM": 3, "NY": 26, "NC": 14, "ND": 1, "OH": 15, "OK": 5, "OR": 6, "PA": 17, "RI": 2, "SC": 7,
    "SD": 1, "TN": 9, "TX": 38, "UT": 4, "VT": 1, "VA": 11, "WA": 10, "WV": 2, "WI": 8, "WY": 1,
}

SENATE_CLASS_2 = frozenset(
    "AL AK AR CO DE GA ID IL IA KS KY LA ME MA MI MN MS MT NE NH NJ NM NC OK OR RI SC SD TN TX VA WV WY"
    .split()
)
SENATE_SPECIALS = frozenset({"FL", "OH"})

_HOUSE_ID = re.compile(rf"{YEAR}-([A-Z]{{2}})-H(AL|\d{{2}})")


def at_large(state: str) -> bool:
    return APPORTIONMENT[state] == 1


def house_race_id(state: str, district: int) -> str:
    seats = APPORTIONMENT[state]
    if not 1 <= district <= seats:
        raise ValueError(f"{state} has {seats} House seat(s), not district {district}")
    return f"{YEAR}-{state}-HAL" if seats == 1 else f"{YEAR}-{state}-H{district:02d}"


def parse_house_race_id(race_id: str) -> tuple[str, int] | None:
    """(state, district) for a valid House race ID, else None. At-large is district 1."""
    match = _HOUSE_ID.fullmatch(race_id)
    if not match or match[1] not in APPORTIONMENT:
        return None
    state, district = match[1], match[2]
    if (district == "AL") != at_large(state):
        return None
    number = 1 if district == "AL" else int(district)
    return (state, number) if 1 <= number <= APPORTIONMENT[state] else None


def district_of(race_id: str) -> int | None:
    """The district number of a House race ID (1 for at-large), None for anything else."""
    parsed = parse_house_race_id(race_id)
    return parsed[1] if parsed else None


def house_race_ids() -> list[str]:
    return [house_race_id(state, n) for state in sorted(APPORTIONMENT)
            for n in range(1, APPORTIONMENT[state] + 1)]


def senate_race_id(state: str) -> str:
    if state in SENATE_SPECIALS:
        return f"{YEAR}-{state}-SEN-SPECIAL"
    if state in SENATE_CLASS_2:
        return f"{YEAR}-{state}-SEN"
    raise ValueError(f"{state} has no {YEAR} Senate race")


_SENATE_ID = re.compile(rf"{YEAR}-([A-Z]{{2}})-SEN(-SPECIAL)?")


def race_identity(race_id: str) -> tuple[str, str, int | None] | None:
    """(state, race_type, district) for a canonical 2026 federal race ID, else None."""
    if house := parse_house_race_id(race_id):
        return house[0], "house", house[1]
    match = _SENATE_ID.fullmatch(race_id)
    if not match:
        return None
    state, special = match[1], bool(match[2])
    if special != (state in SENATE_SPECIALS) or state not in SENATE_CLASS_2 | SENATE_SPECIALS:
        return None
    return state, "senate-special" if special else "senate", None


def senate_race_ids() -> list[str]:
    return [senate_race_id(state) for state in sorted(SENATE_CLASS_2 | SENATE_SPECIALS)]
