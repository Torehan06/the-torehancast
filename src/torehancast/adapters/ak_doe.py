"""Alaska: Division of Elections precinct results, by state House district.

Alaska has no counties. Results are reported by precinct, and every precinct
belongs to one of 40 House districts, which are our units ("1".."40").

Two official formats:

  * ENR precinct CSV (2024 onward, and the 2026 live path):
        https://www.elections.alaska.gov/results/{code}/ENRbyPrecinct.csv
        https://www.elections.alaska.gov/enr26/results/GA_ENR_Precinct_State_of_Alaska.csv
    One row per precinct × contest × candidate, with per-vote-type columns
    (`Election Day_votes`, `Absentee_votes`, `Early Voting_votes`,
    `Question_votes`, `Remote_votes`).
  * "Results per Precinct" text report (2022): UTF-16 tab-separated, one block per
    contest headed "<Contest> (Vote for 1)", candidates as "Name - PARTY", a
    `Total` row at the end of each block, and no vote-type columns.

In both, ballots not cast at a polling place are reported in pooled
pseudo-precincts per district: "District 7 - Absentee", "District 7 - Early
Voting", "District 7  - Question" (questioned = Alaska's provisional ballot),
plus a statewide "HD99 Fed Overseas Absentee" kept as its own unit "99".

The server sends the wrong TLS intermediate; `http.ssl_context()` supplies the
right one. Verification is never disabled.
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from pathlib import Path

from ..candidates import CandidateMap
from ..http import PoliteClient
from ..schema import EARLY, ELECTION_DAY, MAIL, PROVISIONAL, Cell, Snapshot

BASE = "https://www.elections.alaska.gov"
# Where the Aug 2026 primary was published; assumed to carry Nov 3 too. Check
# against the Division's election-night page and swap in config/feeds.yaml if not.
LIVE_URL = f"{BASE}/enr26/results/GA_ENR_Precinct_State_of_Alaska.csv"

# CSV column prefix -> canonical vote type. Alaska's "Absentee" is mail and is
# counted mostly after election night, unlike Iowa's combined "Absentee" (early),
# so this mapping is local rather than in schema._VOTE_TYPE_LABELS.
COLUMNS = {
    "Election Day": ELECTION_DAY,
    "Absentee": MAIL,
    "Early Voting": EARLY,
    "Question": PROVISIONAL,
    "Remote": MAIL,  # always zero so far; warned about if that changes
}
POOLED = {"Absentee": MAIL, "Early Voting": EARLY, "Question": PROVISIONAL}
# Zero-ballot precincts in certified files held 0.6%, 2.1% and 4.8% of their
# district's registration (2024 and 2026 primaries); 6% covers them with margin.
ZERO_PRECINCT_SLACK = 0.06

# "01-600 Ketchikan No. 1" (one 2022 row has "07 010 K Beach"), "District 7 - Absentee",
# "District 7  - Question", "HD99 Fed Overseas Absentee".
_PRECINCT = re.compile(r"^(\d{2})[- ]\d+ ")
_POOLED = re.compile(r"^District (\d+)\s+-\s+(Absentee|Early Voting|Question)$")
_OVERSEAS = re.compile(r"^HD(\d+) Fed Overseas Absentee$")
_PARTY_SUFFIX = re.compile(r"^(.*) - [A-Z]{2,4}$")


class UnknownPrecinct(ValueError):
    """A row name that is neither a precinct nor a known pseudo-precinct."""


def locate(precinct_name: str) -> tuple[str, str | None]:
    """(district, pooled vote type or None for a polling-place precinct)."""
    name = precinct_name.strip()
    if m := _PRECINCT.match(name):
        return str(int(m.group(1))), None
    if m := _POOLED.match(name):
        return str(int(m.group(1))), POOLED[m.group(2)]
    if m := _OVERSEAS.match(name):
        return str(int(m.group(1))), MAIL
    raise UnknownPrecinct(f"unrecognised Alaska precinct name {precinct_name!r}")


def archive_url(code: str, base: str = BASE) -> str:
    """code like '24GENR' or '24PRIM'."""
    return f"{base}/results/{code}/ENRbyPrecinct.csv"


def fetch(client: PoliteClient, url: str = LIVE_URL) -> str:
    return client.get(url).decode("utf-8-sig")


def district_reporting(precincts: dict[str, list[dict]]) -> dict[str, float]:
    """Share of each district's polling-place precincts that have reported.

    `precincts` maps district -> one dict per polling-place precinct in the contest:
    {"ballots": int, "votes": int, "registered": int}. The feed's own
    `Reporting_flag` is 0 on every row even in certified files, so it can't be used.

    A precinct counts as reported once it has ballots, weighted by registered voters
    (one precinct can hold 46% of a district). Some precincts never report: in the
    certified Aug 2026 primary, Kipnuk and Kwigillingok (4.8% of District 38's
    registration) cast no ballots there. So once the precincts still at zero hold
    under ZERO_PRECINCT_SLACK of registration, the district is treated as complete.
    """
    out = {}
    for district, rows in precincts.items():
        registered = sum(max(r["registered"], 1) for r in rows)
        waiting = sum(max(r["registered"], 1) for r in rows if r["ballots"] == 0)
        if not rows or waiting == registered:
            out[district] = 0.0
        else:
            out[district] = 1.0 if waiting < ZERO_PRECINCT_SLACK * registered else 1.0 - waiting / registered
    return out


def parse(text: str, contest: str, cmap: CandidateMap, race: str) -> Snapshot:
    """Either format; the CSV is recognised by its header."""
    text = text.lstrip("﻿")
    if text.startswith("Precinct_name,"):
        return _parse_csv(text, contest, cmap, race)
    return _parse_report(text, contest, cmap, race)


def _snapshot(votes, race, cmap, reporting, warnings) -> Snapshot:
    cells = [Cell(u, vt, dict(v)) for (u, vt), v in sorted(votes.items()) if sum(v.values())]
    return Snapshot("AK", race, None, cells, reporting, warnings=cmap.warnings() + warnings)


def _parse_csv(text: str, contest: str, cmap: CandidateMap, race: str) -> Snapshot:
    votes: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    precincts: dict[str, dict[str, dict]] = defaultdict(dict)
    remote = 0
    for row in csv.DictReader(io.StringIO(text)):
        if row["Contest_title"] != contest:
            continue
        name = row["Precinct_name"]
        district, pooled = locate(name)
        key = cmap.key_for(row["candidate_name"].strip())
        for label, vt in COLUMNS.items():
            n = int(row[f"{label}_votes"] or 0)
            votes[district, vt][key] += n
            remote += n if label == "Remote" else 0
        if pooled is None:
            p = precincts[district].setdefault(
                name, {"ballots": int(row["total_ballots"] or 0), "votes": 0, "registered": int(row["Reg_voters"] or 0)}
            )
            p["votes"] += int(row["total_votes"] or 0)
    reporting = district_reporting({d: list(ps.values()) for d, ps in precincts.items()})
    warnings = [f"{remote} 'Remote' votes booked as mail; check what Remote means"] if remote else []
    return _snapshot(votes, race, cmap, reporting, warnings)


def _parse_report(text: str, contest: str, cmap: CandidateMap, race: str) -> Snapshot:
    """2022 text report: the contest's block, vote type from the row name."""
    lines = text.replace("\r", "").split("\n")
    start = next((i for i, l in enumerate(lines) if l.startswith(f"{contest} (Vote for")), None)
    votes: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    if start is None:
        return _snapshot(votes, race, cmap, {}, [])
    header = next(csv.reader([lines[start + 1]], delimiter="\t"))
    assert header[0] == "Precinct", header
    names = [n.strip() for n in header[1:]]
    keys = [cmap.key_for(m.group(1) if (m := _PARTY_SUFFIX.match(n)) else n) for n in names]
    sums = [0] * len(names)
    for line in lines[start + 2 :]:
        row = next(csv.reader([line], delimiter="\t")) if line.strip() else []
        if not row or not row[0].strip():
            break
        counts = [int(x or 0) for x in row[1 : len(names) + 1]]
        if row[0].strip() == "Total":
            if counts != sums:
                raise ValueError(f"{contest}: rows don't add up to the report's Total row")
            break
        district, pooled = locate(row[0])
        for key, n in zip(keys, counts):
            votes[district, pooled or ELECTION_DAY][key] += n
        sums = [a + b for a, b in zip(sums, counts)]
    return _snapshot(votes, race, cmap, {}, [])


def load_archive(directory: Path, code: str) -> str:
    """`{code}_ENRbyPrecinct.csv` (UTF-8) or `{code}_Results_per_Precinct.txt` (UTF-16)."""
    csv_path = directory / f"{code}_ENRbyPrecinct.csv"
    if csv_path.exists():
        return csv_path.read_text(encoding="utf-8-sig")
    return (directory / f"{code}_Results_per_Precinct.txt").read_text(encoding="utf-16")


# Adapter protocol (see adapters/__init__.py).

def fetch_source(client: PoliteClient, feed) -> str:
    return fetch(client, feed.url)


def final_snapshot(spec: dict, archives: Path, cmap: CandidateMap, key: str) -> Snapshot:
    return parse(load_archive(archives, spec["code"]), spec["contest"], cmap, key)
