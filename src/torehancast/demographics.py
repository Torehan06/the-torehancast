"""Unit demographics used as swing covariates (never shown on the site).

Source: American Community Survey 2023 5-year estimates, from the Census Bureau's
table-based summary files, which need no API key:
https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/

Units are counties, except Alaska, which reports by state House district
(ACS summary level 620, "L8" plan, the districts in use since the 2024 elections).

These are county-level associations — "counties with more X swung more" — and
say nothing about how any individual voter behaves.

    python -m torehancast.demographics GA NC     # build data/demographics/{ST}.csv
"""

from __future__ import annotations

import sys

import pandas as pd

from .elections import ROOT

RAW = ROOT / "data" / "archives" / "acs"
DIR = ROOT / "data" / "demographics"
COLUMNS = ("white_nh", "black_nh", "asian_nh", "hispanic", "median_income", "bachelors_plus", "median_age")

# ACS table → the estimate columns we need.
TABLES = {
    "b03002": ["B03002_E001", "B03002_E003", "B03002_E004", "B03002_E006", "B03002_E012"],
    "b19013": ["B19013_E001"],
    "b15003": ["B15003_E001", "B15003_E022", "B15003_E023", "B15003_E024", "B15003_E025"],
    "b01002": ["B01002_E001"],
}
FIPS = {"GA": "13", "NC": "37", "FL": "12", "TX": "48", "OH": "39", "IA": "19", "KS": "20",
        "SC": "45", "MI": "26", "MN": "27", "ME": "23", "AK": "02", "NE": "31"}


def _prefixes(state: str) -> tuple[str, ...]:
    fips = FIPS[state]
    return (f"620L800US{fips}",) if state == "AK" else (f"0500000US{fips}",)


def _read(table: str, prefixes: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    cols = TABLES[table]
    with open(RAW / f"acsdt5y2023-{table}.dat", encoding="latin-1") as f:
        header = f.readline().rstrip("\n").split("|")
        idx = [header.index(c) for c in cols]
        for line in f:
            if line.startswith(prefixes):
                parts = line.rstrip("\n").split("|")
                rows.append([parts[0]] + [float(parts[i]) if parts[i] not in ("", "null") else float("nan") for i in idx])
    return pd.DataFrame(rows, columns=["GEO_ID", *cols]).set_index("GEO_ID")


def unit_names(state: str, geo_ids: pd.Index) -> pd.Series:
    """GEO_ID → our unit_id: county name upper-cased without 'County'; AK district number."""
    if state == "AK":
        return pd.Series([str(int(g[-3:])) for g in geo_ids], index=geo_ids)
    codes = pd.read_csv(RAW / "national_county2020.txt", sep="|", dtype=str)
    codes = codes[codes.STATE == state]
    name = dict(zip("0500000US" + codes.STATEFP + codes.COUNTYFP, codes.COUNTYNAME))
    return pd.Series([name[g].removesuffix(" County").upper() for g in geo_ids], index=geo_ids)


def build(state: str) -> pd.DataFrame:
    prefixes = _prefixes(state)
    t = pd.concat([_read(table, prefixes) for table in TABLES], axis=1)
    out = pd.DataFrame(
        {
            "unit_id": unit_names(state, t.index),
            "white_nh": t.B03002_E003 / t.B03002_E001,
            "black_nh": t.B03002_E004 / t.B03002_E001,
            "asian_nh": t.B03002_E006 / t.B03002_E001,
            "hispanic": t.B03002_E012 / t.B03002_E001,
            "median_income": t.B19013_E001,
            "bachelors_plus": (t.B15003_E022 + t.B15003_E023 + t.B15003_E024 + t.B15003_E025) / t.B15003_E001,
            "median_age": t.B01002_E001,
        }
    ).reset_index(drop=True)
    DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(DIR / f"{state}.csv", index=False)
    return out


def load(state: str) -> pd.DataFrame | None:
    path = DIR / f"{state}.csv"
    return pd.read_csv(path, dtype={"unit_id": str}) if path.exists() else None


if __name__ == "__main__":
    for st in sys.argv[1:]:
        df = build(st)
        print(st, len(df), "units;", int(df.isna().any(axis=1).sum()), "with missing values")
