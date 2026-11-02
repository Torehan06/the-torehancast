"""Units for House races: counties, or the part of a county inside one district.

A House race whose `unit` in races.yaml is `county-part` keys every unit as
`COUNTY|NN`: the county's name as the feed spells it, then the two-digit district.
A county split between districts is then a different unit in each district's race,
and a whole county is simply its only part (`POLK|03`). The same key is used by the
baseline, the parsed feed (replayed or live) and the demographics join, so the three
unit sets are identical by construction. Adapters keep emitting plain county names;
`relabel` turns them into county parts.

Known weakness: the ACS covariates are county-level, so every part of a split county
gets its whole county's demographics, even where the district line separates, say,
a city from its suburbs. Partisanship and size covariates come from the baseline, so
they are the part's own.
"""

from __future__ import annotations

import pandas as pd

from ..schema import Cell, Snapshot

SEP = "|"
COUNTY = "county"
COUNTY_PART = "county-part"


def county_part(county: str, district: int) -> str:
    """`county_part("POLK", 3)` → `"POLK|03"`. Already a county part: unchanged."""
    return county if SEP in county else f"{county}{SEP}{district:02d}"


def county_of(unit_id: str) -> str:
    """The county a unit lies in: `"POLK|03"` → `"POLK"`, `"POLK"` → `"POLK"`."""
    return unit_id.split(SEP, 1)[0]


def relabel(snap: Snapshot, district: int) -> Snapshot:
    """A district contest's snapshot, county names → county parts of `district`."""
    def part(u: str) -> str:
        return county_part(u, district)

    return Snapshot(
        snap.state,
        snap.race,
        snap.as_of,
        [Cell(part(c.unit_id), c.vote_type, c.votes) for c in snap.cells],
        {part(u): v for u, v in snap.unit_reporting.items()},
        {(part(u), vt): v for (u, vt), v in snap.cell_complete.items()},
        list(snap.warnings),
    )


def relabel_frame(df: pd.DataFrame, district: int) -> pd.DataFrame:
    """A baseline frame (unit_id column), county names → county parts of `district`."""
    return df.assign(unit_id=[county_part(u, district) for u in df.unit_id])


def demographics_for(demo: pd.DataFrame | None, unit_ids) -> pd.DataFrame | None:
    """One demographics row per county part, copied from its county.

    Raises if a unit's county has no row: the model would silently give it the state
    mean, and the unit sets must match.
    """
    if demo is None:
        return None
    by_county = demo.set_index("unit_id")
    units = sorted(set(unit_ids))
    missing = sorted({county_of(u) for u in units} - set(by_county.index))
    if missing:
        raise ValueError(f"no demographics row for {missing}")
    rows = by_county.loc[[county_of(u) for u in units]].reset_index(drop=True)
    return rows.assign(unit_id=units)[["unit_id", *[c for c in demo.columns if c != "unit_id"]]]
