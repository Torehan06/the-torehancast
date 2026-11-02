"""Minnesota: Secretary of State semicolon-delimited results files.

Minnesota publishes headerless, semicolon-delimited text files at

    https://electionresultsfiles.sos.mn.gov/{YYYYMMDD}/{filename}

(Directory listings return 403; files are fetched directly.)
County results files (`USPresCty.txt`, `ussenatecty.txt`, `allracesbycounty.txt`)
have 16 semicolon-separated columns:

    0  State ("MN")
    1  County ID ("01".."87", matching Cntytbl.txt)
    2  Precinct (empty in county files)
    3  Office ID ("0101" Pres, "0102" U.S. Senator)
    4  Office Name ("U.S. President & Vice President", "U.S. Senator")
    5  District
    6  Candidate Order Code
    7  Candidate Name
    8  Suffix
    9  Incumbent Code
    10 Party ("R", "DFL", etc.)
    11 Precincts Reporting
    12 Total Precincts
    13 Votes
    14 Vote %
    15 Total Votes in Contest for County

Minnesota does not break county counts out by vote type, so every cell has
`vote_type = ALL`.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from pathlib import Path

from .. import results_only
from ..candidates import CandidateMap
from ..schema import ALL, Cell, Snapshot

BASE = "https://electionresultsfiles.sos.mn.gov"

# Canonical 87 Minnesota county IDs ("01".."87") from Cntytbl.txt.
COUNTIES: dict[str, str] = {
    "01": "AITKIN", "02": "ANOKA", "03": "BECKER", "04": "BELTRAMI", "05": "BENTON",
    "06": "BIG STONE", "07": "BLUE EARTH", "08": "BROWN", "09": "CARLTON", "10": "CARVER",
    "11": "CASS", "12": "CHIPPEWA", "13": "CHISAGO", "14": "CLAY", "15": "CLEARWATER",
    "16": "COOK", "17": "COTTONWOOD", "18": "CROW WING", "19": "DAKOTA", "20": "DODGE",
    "21": "DOUGLAS", "22": "FARIBAULT", "23": "FILLMORE", "24": "FREEBORN", "25": "GOODHUE",
    "26": "GRANT", "27": "HENNEPIN", "28": "HOUSTON", "29": "HUBBARD", "30": "ISANTI",
    "31": "ITASCA", "32": "JACKSON", "33": "KANABEC", "34": "KANDIYOHI", "35": "KITTSON",
    "36": "KOOCHICHING", "37": "LAC QUI PARLE", "38": "LAKE", "39": "LAKE OF THE WOODS",
    "40": "LE SUEUR", "41": "LINCOLN", "42": "LYON", "43": "MCLEOD", "44": "MAHNOMEN",
    "45": "MARSHALL", "46": "MARTIN", "47": "MEEKER", "48": "MILLE LACS", "49": "MORRISON",
    "50": "MOWER", "51": "MURRAY", "52": "NICOLLET", "53": "NOBLES", "54": "NORMAN",
    "55": "OLMSTED", "56": "OTTER TAIL", "57": "PENNINGTON", "58": "PINE", "59": "PIPESTONE",
    "60": "POLK", "61": "POPE", "62": "RAMSEY", "63": "RED LAKE", "64": "REDWOOD",
    "65": "RENVILLE", "66": "RICE", "67": "ROCK", "68": "ROSEAU", "69": "ST. LOUIS",
    "70": "SCOTT", "71": "SHERBURNE", "72": "SIBLEY", "73": "STEARNS", "74": "STEELE",
    "75": "STEVENS", "76": "SWIFT", "77": "TODD", "78": "TRAVERSE", "79": "WABASHA",
    "80": "WADENA", "81": "WASECA", "82": "WASHINGTON", "83": "WATONWAN", "84": "WILKIN",
    "85": "WINONA", "86": "WRIGHT", "87": "YELLOW MEDICINE",
}


def results_url(election_date: str, filename: str = "ussenatecty.txt", base: str = BASE) -> str:
    """election_date like '2024-11-05'."""
    return f"{base}/{election_date.replace('-', '')}/{filename}"


def county_table_url(election_date: str, base: str = BASE) -> str:
    return results_url(election_date, "Cntytbl.txt", base)


def parse_counties(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter=";"):
        if len(row) >= 2 and row[0].strip():
            out[row[0].strip().zfill(2)] = row[1].strip().upper()
    return out


def parse(
    text: str,
    contest: str,
    cmap: CandidateMap,
    race: str,
    counties: dict[str, str] | None = None,
) -> Snapshot:
    county_map = counties or COUNTIES
    votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    reporting: dict[str, float] = {}

    for row in csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter=";"):
        if len(row) < 14:
            continue
        office_id, office_name = row[3].strip(), row[4].strip()
        if contest not in (office_name, office_id):
            continue
        cid = row[1].strip().zfill(2)
        county = county_map[cid]
        key = cmap.key_for(row[7].strip())
        votes[county][key] += int(row[13] or 0)
        total = int(row[12] or 0)
        if total > 0:
            reporting[county] = int(row[11] or 0) / total

    cells = [Cell(county, ALL, dict(v)) for county, v in sorted(votes.items())]
    return Snapshot("MN", race, None, cells, reporting, warnings=cmap.warnings())


def load_archive(directory: Path, election_date: str, prefix: str = "USPresCty") -> str:
    compact = election_date.replace("-", "")
    return (directory / f"{prefix}_{compact}.txt").read_text(encoding="utf-8-sig")


# Adapter protocol (see adapters/__init__.py).

def fetch_source(client, feed) -> str:
    return client.get(feed.url).decode("utf-8-sig")


def final_snapshot(spec: dict, archives: Path, cmap: CandidateMap, key: str) -> Snapshot:
    return parse(load_archive(archives, spec["date"]), spec["contest"], cmap, key)


def parse_all_contests(text: str, contests) -> dict[str, results_only.ContestTotals]:
    """Every results-only contest in one pass; a contest matches by office name or ID,
    as in `parse`. Reporting is counted once per county row group."""
    choices: dict[str, list[results_only.Choice]] = defaultdict(list)
    units: dict[str, dict[str, tuple[int, int]]] = defaultdict(dict)
    for row in csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter=";"):
        if len(row) < 14:
            continue
        office_id, office_name = row[3].strip(), row[4].strip()
        contest = next((c for c in contests if c.contest in (office_name, office_id)), None)
        if contest is None or not contest.contest:
            continue
        choices[contest.race_id].append(results_only.Choice(row[7].strip(), row[10].strip(), int(row[13] or 0)))
        units[contest.race_id][row[1].strip().zfill(2)] = (int(row[11] or 0), int(row[12] or 0))
    sides = {c.race_id: c.sides for c in contests}
    return {
        race_id: results_only.totals(found, sides[race_id], results_only.fraction(
            sum(r for r, _ in units[race_id].values()), sum(t for _, t in units[race_id].values())))
        for race_id, found in choices.items()
    }
