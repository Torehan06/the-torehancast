"""Florida: past results rebuilt on the 2026 congressional lines, from DOS precinct files.

Florida redrew its map in May 2026 (plan EOGPCRP2026), and no official source
publishes earlier results on the new lines. So a redrawn district's baseline is
rebuilt from the Division of Elections' precinct-level results files:

1. The enacted plan's block file says which counties lie wholly in one district. Such
   a county part is simply the county total: no precinct join can misplace its votes.
2. For a split county, the 2026 primary file gives every 2026 precinct its congressional
   district (the `Representative in Congress` contests carry it). A precinct listed under
   two districts is divided by its House primary ballots in each.
3. A past general's file gives President votes per precinct, joined on (county, precinct
   ID). Counties re-precinct after every map, so a joined pair can be a different patch of
   ground with the same number. A pair whose registered voters changed by more than
   `MAX_REGISTRATION_CHANGE` (relative to its county's overall change) counts as unmatched.
4. A split county with more than `MAX_UNMATCHED` of its vote unmatched stops the build.
   Below that, the unmatched votes are spread over the county's parts in proportion to
   its matched votes, so county totals stay exact.

The result is one cell per county part of the district, keyed by the county's name
as the live extract spells it (the replay harness turns that into `COUNTY|NN`).
Archive-only: there is no live feed in this format.
"""

from __future__ import annotations

import csv
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
HOUSE_CONTEST = "Representative in Congress"
# Rows that count ballots, not votes. Seminole's 2016 file has its own spelling.
NON_VOTES = frozenset({"overvotes", "undervotes", "times over voted", "times blank voted"})

MAX_UNMATCHED = 0.01  # share of a split county's vote that may lack a 2026 district
MAX_REGISTRATION_CHANGE = 0.25  # beyond this a same-ID precinct is a different place


class CrosswalkError(ValueError):
    """The precinct join is too weak to trust; the message has the per-county report."""


def norm_precinct(value: str, county: str = "") -> str:
    """The same precinct across files: '0101' = '101'; letters and suffixes are kept.

    Two counties change spelling between years: Collier's 2026 file writes PCT101 for 101,
    and Miami-Dade's 001.0 is 001 in some years and 0010 in others.
    """
    text = str(value).strip().upper()
    if county == "CLL":
        text = re.sub(r"^PCT\s*", "", text)
    if county == "DAD" and re.fullmatch(r"\d{3}", text):
        text += "0"
    return re.sub(r"^0+(?=\d)", "", text)


def read_precinct_text(text: str) -> pd.DataFrame:
    rows = [line.split("\t") for line in text.lstrip("\ufeff").splitlines() if line.strip()]
    if bad := [r for r in rows if len(r) != len(COLUMNS)]:
        raise ValueError(f"precinct file: expected {len(COLUMNS)} fields, got {len(bad[0])}: {bad[0][:6]}")
    df = pd.DataFrame(rows, columns=COLUMNS)
    for col in ("registered", "votes"):
        df[col] = pd.to_numeric(df[col].str.strip().replace("", "0")).astype(int)
    for col in ("county_code", "county_name", "contest", "district", "candidate"):
        df[col] = df[col].str.strip()
    df["county_code"] = df.county_code.str.upper()
    df["precinct"] = [norm_precinct(p, c) for p, c in zip(df.precinct, df.county_code)]
    return df


def read_precinct_archive(path: Path) -> pd.DataFrame:
    """A DOS precinct zip (one text file per county) or a single extracted text file.

    `*Recount*` files are skipped. They restate one recounted contest, never President
    (checked for 2016, 2020, 2024), and carry a header row.
    """
    if path.suffix.lower() != ".zip":
        return read_precinct_text(path.read_text(encoding="utf-8-sig", errors="replace"))
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if n.lower().endswith(".txt") and "recount" not in n.lower())
        if not names:
            raise ValueError(f"{path.name}: no .txt files inside")
        return pd.concat([read_precinct_text(z.read(n).decode("latin-1").removeprefix("\xef\xbb\xbf")) for n in names],
                         ignore_index=True)


def district_number(value: str) -> int:
    """'22', '022' or 'District 22' → 22."""
    digits = re.findall(r"\d+", value or "")
    if len(digits) != 1:
        raise ValueError(f"unreadable congressional district {value!r}")
    return int(digits[0])


def contest_rows(df: pd.DataFrame, contest: str) -> pd.DataFrame:
    """One contest, without over- and undervotes. Case-blind: Seminole's 2016 file is in capitals."""
    rows = df[df.contest.str.casefold() == contest.casefold()]
    return rows[~rows.candidate.str.casefold().isin(NON_VOTES)]


def assignment(primary: pd.DataFrame, contest: str = HOUSE_CONTEST) -> pd.DataFrame:
    """2026 precinct → congressional district, one row per (precinct, district).

    Every precinct of a district appears in that district's primary contests (with
    zero votes where nobody voted). A precinct with no House contest at all lies in a
    district that held no primary, so it gets district 0: known, and in none of the
    districts with a primary. `share` divides a precinct listed under two districts by
    its ballots in each, over- and undervotes included.
    """
    house = primary[primary.contest.str.casefold() == contest.casefold()]
    if house.empty:
        raise ValueError(f"no {contest!r} rows in the 2026 primary file")
    ballots = (house.assign(district=house.district.map(district_number))
               .groupby(["county_code", "precinct", "district"], as_index=False).votes.sum())
    total = ballots.groupby(["county_code", "precinct"]).votes.transform("sum")
    count = ballots.groupby(["county_code", "precinct"]).votes.transform("size")
    ballots["share"] = (ballots.votes / total.where(total > 0)).fillna(1.0 / count)
    reg = primary.groupby(["county_code", "precinct"], as_index=False).registered.max()
    out = reg.merge(ballots.drop(columns="votes"), on=["county_code", "precinct"], how="left")
    return out.assign(district=out.district.fillna(0).astype(int), share=out.share.fillna(1.0))[
        ["county_code", "precinct", "district", "share", "registered"]]


@dataclass(frozen=True)
class CountyMatch:
    county_code: str
    votes: int
    unmatched_votes: int  # in precincts with no 2026 counterpart
    moved_votes: int  # in same-ID precincts whose registration jumped
    split_votes: int = 0  # in 2026 precincts divided between districts by ballots
    unchecked_votes: int = 0  # matched, but a file reports no registration to compare

    @property
    def unmatched_share(self) -> float:
        return (self.unmatched_votes + self.moved_votes) / self.votes if self.votes else 0.0

    def line(self) -> str:
        return (f"{self.county_code}: {self.unmatched_share:.2%} unmatched "
                f"({self.unmatched_votes:,} no 2026 precinct, {self.moved_votes:,} boundary moved, "
                f"of {self.votes:,}; {self.split_votes:,} in split precincts, "
                f"{self.unchecked_votes:,} without a registration check)")


def match_report(year: pd.DataFrame, assign: pd.DataFrame, counties: set[str],
                 max_registration_change: float = MAX_REGISTRATION_CHANGE,
                 ) -> tuple[pd.DataFrame, dict[str, CountyMatch]]:
    """Each precinct's status ('ok', 'moved', 'unmatched'), plus the report for `counties`."""
    votes = year.groupby(["county_code", "precinct"], as_index=False).agg(
        votes=("votes", "sum"), registered=("registered", "max"))
    known = assign.groupby(["county_code", "precinct"], as_index=False).agg(
        registered_2026=("registered", "max"), parts=("district", "size"))
    joined = votes.merge(known, on=["county_code", "precinct"], how="left")

    # Registration change relative to the county's own change, so countywide growth or
    # list maintenance between the two books doesn't flag every precinct.
    has = joined.parts.notna()
    found = has & (joined.registered > 0) & (joined.registered_2026 > 0)
    grouped = joined[found].groupby("county_code")
    county_ratio = grouped.registered.sum() / grouped.registered_2026.sum()
    ratio = joined.registered / joined.registered_2026 / joined.county_code.map(county_ratio)
    moved = found & (np.abs(np.log(ratio.where(found, 1.0))) > np.log1p(max_registration_change))
    joined["status"] = np.where(~has, "unmatched", np.where(moved, "moved", "ok"))

    report = {}
    for code in sorted(counties):
        c = joined[joined.county_code == code]
        by = c.groupby("status").votes.sum()
        report[code] = CountyMatch(
            code, int(c.votes.sum()), int(by.get("unmatched", 0)), int(by.get("moved", 0)),
            int(c.loc[c.parts > 1, "votes"].sum()),
            int(c.loc[(c.status == "ok") & ~found[c.index], "votes"].sum()),
        )
    return joined, report


def crosswalk(year: pd.DataFrame, assign: pd.DataFrame, counties: set[str],
              max_unmatched: float = MAX_UNMATCHED,
              max_registration_change: float = MAX_REGISTRATION_CHANGE,
              ) -> tuple[pd.DataFrame, dict[str, CountyMatch]]:
    """Votes per (county, 2026 district, side key), plus the match report for `counties`.

    `year` holds one contest's rows with a `side` column. Raises CrosswalkError
    listing every county in `counties` over `max_unmatched`.
    """
    joined, report = match_report(year, assign, counties, max_registration_change)
    if bad := [m for m in report.values() if m.unmatched_share > max_unmatched]:
        raise CrosswalkError(
            f"precinct join over the {max_unmatched:.0%} limit in {len(bad)} county(ies):\n  "
            + "\n  ".join(m.line() for m in bad)
        )

    per_precinct = year.groupby(["county_code", "precinct", "side"], as_index=False).votes.sum()
    ok = joined.loc[joined.status == "ok", ["county_code", "precinct"]]
    placed = (per_precinct.merge(ok, on=["county_code", "precinct"])
              .merge(assign[["county_code", "precinct", "district", "share"]], on=["county_code", "precinct"]))
    placed["votes"] = placed.votes * placed.share
    parts = placed.groupby(["county_code", "district", "side"], as_index=False).votes.sum()

    # Spread each county's unmatched votes over its parts by matched share, per side.
    county_side = per_precinct.groupby(["county_code", "side"]).votes.sum()
    matched_side = parts.groupby(["county_code", "side"]).votes.transform("sum")
    target = parts.set_index(["county_code", "side"]).index.map(county_side.to_dict())
    parts["votes"] = (parts.votes * np.asarray(target, dtype=float)
                      / matched_side.where(matched_side > 0, 1)).round().astype(int)
    return parts, report


def county_names(extract_text: str) -> dict[str, str]:
    """County code → the live extract's spelling, upper case ('DAD' → 'MIAMI-DADE')."""
    return {r["CountyCode"].strip().upper(): r["CountyName"].strip().upper()
            for r in csv.DictReader(io.StringIO(extract_text), delimiter="\t")}


# County FIPS (the census block GEOID's characters 3-5) → the live extract's spelling.
# Dade's old 025 became Miami-Dade's 086 in 1997.
FIPS = {
    "001": "ALACHUA", "003": "BAKER", "005": "BAY", "007": "BRADFORD", "009": "BREVARD", "011": "BROWARD",
    "013": "CALHOUN", "015": "CHARLOTTE", "017": "CITRUS", "019": "CLAY", "021": "COLLIER", "023": "COLUMBIA",
    "027": "DESOTO", "029": "DIXIE", "031": "DUVAL", "033": "ESCAMBIA", "035": "FLAGLER", "037": "FRANKLIN",
    "039": "GADSDEN", "041": "GILCHRIST", "043": "GLADES", "045": "GULF", "047": "HAMILTON", "049": "HARDEE",
    "051": "HENDRY", "053": "HERNANDO", "055": "HIGHLANDS", "057": "HILLSBOROUGH", "059": "HOLMES",
    "061": "INDIAN RIVER", "063": "JACKSON", "065": "JEFFERSON", "067": "LAFAYETTE", "069": "LAKE", "071": "LEE",
    "073": "LEON", "075": "LEVY", "077": "LIBERTY", "079": "MADISON", "081": "MANATEE", "083": "MARION",
    "085": "MARTIN", "086": "MIAMI-DADE", "087": "MONROE", "089": "NASSAU", "091": "OKALOOSA",
    "093": "OKEECHOBEE", "095": "ORANGE", "097": "OSCEOLA", "099": "PALM BEACH", "101": "PASCO",
    "103": "PINELLAS", "105": "POLK", "107": "PUTNAM", "109": "ST. JOHNS", "111": "ST. LUCIE",
    "113": "SANTA ROSA", "115": "SARASOTA", "117": "SEMINOLE", "119": "SUMTER", "121": "SUWANNEE",
    "123": "TAYLOR", "125": "UNION", "127": "VOLUSIA", "129": "WAKULLA", "131": "WALTON", "133": "WASHINGTON",
}


def plan_districts(block_file_text: str) -> dict[str, set[int]]:
    """County → its districts under the enacted plan. Lines are `GEOID,district`."""
    out: dict[str, set[int]] = {}
    for line in block_file_text.splitlines():
        geoid, _, district = line.strip().partition(",")
        if district:
            out.setdefault(FIPS[geoid[2:5]], set()).add(int(district))
    return out


def plan_counties(block_file_text: str, district: int) -> set[str]:
    """The counties the enacted plan puts (partly) in `district`."""
    return {c for c, ds in plan_districts(block_file_text).items() if district in ds}


def district_snapshot(year: pd.DataFrame, assign: pd.DataFrame, plan: dict[str, set[int]], district: int,
                      contest: str, cmap: CandidateMap, names: dict[str, str], race: str) -> Snapshot:
    rows = contest_rows(year, contest)
    if rows.empty:
        raise ValueError(f"no {contest!r} rows in the precinct file")
    rows = rows.assign(side=rows.candidate.map(cmap.key_for))
    codes = {name: code for code, name in names.items()}
    counties = {codes[c] for c, ds in plan.items() if district in ds}
    if not counties:
        raise CrosswalkError(f"district {district}: not in the enacted plan")
    found = set(assign.loc[assign.district == district, "county_code"])
    if found != counties:
        raise CrosswalkError(f"district {district}: the 2026 primary lists counties {sorted(found)}, "
                             f"the enacted plan {sorted(counties)}")
    whole = {c for c in counties if plan[names[c]] == {district}}
    votes: dict[str, dict[str, int]] = {}
    for code in whole:
        totals = rows[rows.county_code == code].groupby("side").votes.sum()
        votes[code] = {s: int(v) for s, v in totals.items()}
    split = counties - whole
    report: dict[str, CountyMatch] = {}
    if split:
        parts, report = crosswalk(rows, assign, split)
        for code, g in parts[(parts.district == district) & parts.county_code.isin(split)].groupby("county_code"):
            votes[code] = {s: int(v) for s, v in zip(g.side, g.votes)}
    cells = [Cell(names[code], ALL, v) for code, v in sorted(votes.items(), key=lambda kv: names[kv[0]])]
    warnings = cmap.warnings() + [m.line() for m in report.values()]
    return Snapshot("FL", race, None, cells, {c.unit_id: 1.0 for c in cells}, warnings=warnings)


# Adapter protocol (see adapters/__init__.py).

def fetch_source(client, feed):
    raise NotImplementedError("fl_precinct is archive-only; the live feed is fl_dos")


def parse(document, contest, cmap, race):
    raise NotImplementedError("fl_precinct is archive-only; the live feed is fl_dos")


def county_snapshot(year: pd.DataFrame, contest: str, cmap: CandidateMap, names: dict[str, str],
                    race: str) -> Snapshot:
    """Whole-county totals of one contest: no crosswalk involved."""
    rows = contest_rows(year, contest)
    if rows.empty:
        raise ValueError(f"no {contest!r} rows in the precinct file")
    rows = rows.assign(side=rows.candidate.map(cmap.key_for))
    totals = rows.groupby(["county_code", "side"]).votes.sum()
    cells = [Cell(names[code], ALL, {s: int(v) for s, v in g.droplevel(0).items()})
             for code, g in sorted(totals.groupby(level=0), key=lambda kv: names[kv[0]])]
    return Snapshot("FL", race, None, cells, {c.unit_id: 1.0 for c in cells}, warnings=cmap.warnings())


def final_snapshot(spec: dict, archives: Path, cmap: CandidateMap, key: str) -> Snapshot:
    """spec: `file` (this election's precinct archive), `names` (an extract that spells
    the counties), `contest`; plus `district`, `crosswalk` (the 2026 primary's precinct
    archive) and `plan` (the enacted plan's block file) for a district on the 2026 lines.
    Without `district`: county totals."""
    year = _read(archives / spec["file"])
    names = county_names((archives / spec["names"]).read_text(encoding="latin-1"))
    if "district" not in spec:
        return county_snapshot(year, spec["contest"], cmap, names, key)
    assign = assignment(_read(archives / spec["crosswalk"]))
    plan = plan_districts((archives / spec["plan"]).read_text(encoding="latin-1"))
    return district_snapshot(year, assign, plan, int(spec["district"]), spec["contest"], cmap, names, key)


_CACHE: dict[Path, pd.DataFrame] = {}


def _read(path: Path) -> pd.DataFrame:
    if path not in _CACHE:
        _CACHE[path] = read_precinct_archive(path)
    return _CACHE[path]
