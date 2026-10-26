"""Florida: past results rebuilt on the 2026 congressional lines, from DOS precinct files.

Florida redrew its map in May 2026 (plan EOGPCRP2026), and no official source
publishes earlier results on the new lines. So a redrawn district's baseline is
rebuilt from the Division of Elections' precinct-level results files:

1. The 2026 primary file gives every 2026 precinct its congressional district (the
   `United States Representative` contests carry it).
2. A past general's file gives President votes per precinct.
3. Precincts are joined on (county, precinct ID). Counties re-precinct after every
   map, so a joined pair can be a different patch of ground with the same number. A
   pair whose registered voters changed by more than `MAX_REGISTRATION_CHANGE`
   (relative to its county's overall change) is treated as unmatched.
4. Any county touching a modeled district with more than `MAX_UNMATCHED` of its vote
   unmatched stops the build. Below that, the unmatched votes are spread over the
   county's parts in proportion to its matched votes, so county totals stay exact.

The result is one cell per county part of the district, keyed by the county's name
as the live extract spells it (the replay harness turns that into `COUNTY|NN`).
Archive-only: there is no live feed in this format.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..candidates import CandidateMap
from ..schema import ALL, Cell, Snapshot

# The precinct files are tab-separated without a header row (DOS "Precinct-Level
# Election Results: data definitions and field codes").
COLUMNS = (
    "county_code", "county_name", "election_number", "election_date", "election_name",
    "precinct", "polling_location", "registered", "registered_rep", "registered_dem",
    "registered_other", "contest", "district", "contest_code", "candidate", "party",
    "voter_id", "doe_number", "votes",
)
HOUSE_CONTEST = "United States Representative"

MAX_UNMATCHED = 0.01  # share of a county's vote that may lack a 2026 district
MAX_REGISTRATION_CHANGE = 0.25  # beyond this a same-ID precinct is a different place


class CrosswalkError(ValueError):
    """The precinct join is too weak to trust; the message has the per-county report."""


def norm_precinct(value: str) -> str:
    """'0101' and '101' are the same precinct; letters and suffixes are kept."""
    return re.sub(r"^0+(?=\d)", "", str(value).strip().upper())


def read_precinct_text(text: str) -> pd.DataFrame:
    rows = [line.split("\t") for line in text.splitlines() if line.strip()]
    if bad := [r for r in rows if len(r) != len(COLUMNS)]:
        raise ValueError(f"precinct file: expected {len(COLUMNS)} fields, got {len(bad[0])}: {bad[0][:6]}")
    df = pd.DataFrame(rows, columns=COLUMNS)
    for col in ("registered", "votes"):
        df[col] = pd.to_numeric(df[col].str.strip().replace("", "0")).astype(int)
    for col in ("county_code", "county_name", "contest", "district", "candidate"):
        df[col] = df[col].str.strip()
    df["county_code"] = df.county_code.str.upper()
    df["precinct"] = df.precinct.map(norm_precinct)
    return df


def read_precinct_archive(path: Path) -> pd.DataFrame:
    """A DOS precinct zip (one text file per county) or a single extracted text file."""
    if path.suffix.lower() != ".zip":
        return read_precinct_text(path.read_text(encoding="latin-1"))
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if n.lower().endswith(".txt"))
        if not names:
            raise ValueError(f"{path.name}: no .txt files inside")
        return pd.concat(
            [read_precinct_text(io.TextIOWrapper(z.open(n), encoding="latin-1").read()) for n in names],
            ignore_index=True,
        )


def district_number(value: str) -> int:
    """'22', '022' or 'District 22' → 22."""
    digits = re.findall(r"\d+", value or "")
    if len(digits) != 1:
        raise ValueError(f"unreadable congressional district {value!r}")
    return int(digits[0])


def assignment(primary: pd.DataFrame, contest: str = HOUSE_CONTEST) -> pd.DataFrame:
    """2026 precinct → congressional district, with its registered voters.

    Every precinct of a district appears in that district's primary contests (with
    zero votes where nobody voted). A precinct with no House contest at all lies in a
    district that held no primary, so it gets district 0: known, and in none of the
    districts with a primary. A precinct listed under two districts would be a split
    precinct, which the join can't divide, so it raises.
    """
    house = primary[primary.contest == contest]
    if house.empty:
        raise ValueError(f"no {contest!r} rows in the 2026 primary file")
    pairs = house.assign(district=house.district.map(district_number))[
        ["county_code", "precinct", "district"]].drop_duplicates()
    if (split := pairs[pairs.duplicated(["county_code", "precinct"], keep=False)]).size:
        raise CrosswalkError(f"2026 precincts in two districts: {split.head(10).to_dict('records')}")
    reg = primary.groupby(["county_code", "precinct"], as_index=False).registered.max()
    out = reg.merge(pairs, on=["county_code", "precinct"], how="left")
    return out.assign(district=out.district.fillna(0).astype(int))[
        ["county_code", "precinct", "district", "registered"]]


@dataclass(frozen=True)
class CountyMatch:
    county_code: str
    votes: int
    unmatched_votes: int  # in precincts with no 2026 counterpart
    moved_votes: int  # in same-ID precincts whose registration jumped

    @property
    def unmatched_share(self) -> float:
        return (self.unmatched_votes + self.moved_votes) / self.votes if self.votes else 0.0

    def line(self) -> str:
        return (f"{self.county_code}: {self.unmatched_share:.2%} unmatched "
                f"({self.unmatched_votes:,} no 2026 precinct, {self.moved_votes:,} boundary moved, "
                f"of {self.votes:,})")


def crosswalk(year: pd.DataFrame, assign: pd.DataFrame, counties: set[str],
              max_unmatched: float = MAX_UNMATCHED,
              max_registration_change: float = MAX_REGISTRATION_CHANGE,
              ) -> tuple[pd.DataFrame, dict[str, CountyMatch]]:
    """Votes per (county, 2026 district, side key), plus the match report for `counties`.

    `year` holds one contest's rows with a `side` column. Raises CrosswalkError
    listing every county in `counties` over `max_unmatched`.
    """
    per_precinct = year.groupby(["county_code", "precinct", "side"], as_index=False).votes.sum()
    reg = year.groupby(["county_code", "precinct"], as_index=False).registered.max()
    joined = reg.merge(assign, on=["county_code", "precinct"], how="left", suffixes=("", "_2026"))

    # Registration change relative to the county's own change, so countywide growth or
    # list maintenance between the two books doesn't flag every precinct.
    found = joined.district.notna() & (joined.registered > 0) & (joined.registered_2026 > 0)
    county_ratio = (joined[found].groupby("county_code").registered.sum()
                    / joined[found].groupby("county_code").registered_2026.sum())
    ratio = joined.registered / joined.registered_2026 / joined.county_code.map(county_ratio)
    moved = found & (np.abs(np.log(ratio.where(found, 1.0))) > np.log1p(max_registration_change))
    joined["status"] = np.where(~joined.district.notna(), "unmatched", np.where(moved, "moved", "ok"))

    votes = per_precinct.merge(joined[["county_code", "precinct", "district", "status"]],
                               on=["county_code", "precinct"], how="left")
    totals = votes.groupby(["county_code", "status"]).votes.sum().unstack(fill_value=0)
    report = {}
    for code in sorted(counties):
        row = totals.loc[code] if code in totals.index else pd.Series(dtype=int)
        report[code] = CountyMatch(code, int(row.sum()), int(row.get("unmatched", 0)), int(row.get("moved", 0)))
    if bad := [m for m in report.values() if m.unmatched_share > max_unmatched]:
        raise CrosswalkError(
            f"precinct join over the {max_unmatched:.0%} limit in {len(bad)} county(ies):\n  "
            + "\n  ".join(m.line() for m in bad)
        )

    # Spread each county's unmatched votes over its parts by matched share, per side.
    ok = votes[votes.status == "ok"].assign(district=lambda d: d.district.astype(int))
    parts = ok.groupby(["county_code", "district", "side"], as_index=False).votes.sum()
    county_side = votes.groupby(["county_code", "side"]).votes.sum()
    matched_side = parts.groupby(["county_code", "side"]).votes.transform("sum")
    target = parts.set_index(["county_code", "side"]).index.map(county_side.to_dict())
    parts["votes"] = (parts.votes * np.asarray(target, dtype=float)
                      / matched_side.where(matched_side > 0, 1)).round().astype(int)
    return parts, report


def district_counties(assign: pd.DataFrame, district: int) -> set[str]:
    return set(assign.loc[assign.district == district, "county_code"])


def county_names(extract_text: str) -> dict[str, str]:
    """County code → the live extract's spelling, upper case ('DAD' → 'MIAMI-DADE')."""
    import csv
    return {r["CountyCode"].strip().upper(): r["CountyName"].strip().upper()
            for r in csv.DictReader(io.StringIO(extract_text), delimiter="\t")}


def district_snapshot(year: pd.DataFrame, assign: pd.DataFrame, district: int, contest: str,
                      cmap: CandidateMap, names: dict[str, str], race: str) -> Snapshot:
    rows = year[year.contest == contest]
    if rows.empty:
        raise ValueError(f"no {contest!r} rows in the precinct file")
    rows = rows.assign(side=rows.candidate.map(cmap.key_for))
    counties = district_counties(assign, district)
    if not counties:
        raise CrosswalkError(f"district {district}: no 2026 precincts in the primary file")
    parts, report = crosswalk(rows, assign, counties)
    mine = parts[parts.district == district]
    cells = []
    for code, g in sorted(mine.groupby("county_code"), key=lambda kv: names[kv[0]]):
        cells.append(Cell(names[code], ALL, {s: int(v) for s, v in zip(g.side, g.votes)}))
    warnings = cmap.warnings() + [m.line() for m in report.values()]
    return Snapshot("FL", race, None, cells, {c.unit_id: 1.0 for c in cells}, warnings=warnings)


# Adapter protocol (see adapters/__init__.py).

def fetch_source(client, feed):
    raise NotImplementedError("fl_precinct is archive-only; the live feed is fl_dos")


def parse(document, contest, cmap, race):
    raise NotImplementedError("fl_precinct is archive-only; the live feed is fl_dos")


def final_snapshot(spec: dict, archives: Path, cmap: CandidateMap, key: str) -> Snapshot:
    """spec: `file` (this election's precinct archive), `crosswalk` (the 2026 primary's),
    `names` (an extract that spells the counties), `contest`, `district`."""
    year = _read(archives / spec["file"])
    assign = assignment(_read(archives / spec["crosswalk"]))
    names = county_names((archives / spec["names"]).read_text(encoding="latin-1"))
    return district_snapshot(year, assign, int(spec["district"]), spec["contest"], cmap, names, key)


_CACHE: dict[Path, pd.DataFrame] = {}


def _read(path: Path) -> pd.DataFrame:
    if path not in _CACHE:
        _CACHE[path] = read_precinct_archive(path)
    return _CACHE[path]
