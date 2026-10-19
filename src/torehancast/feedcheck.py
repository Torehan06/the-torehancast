"""Can this machine reach each state's official results feed?

Run from the US poller VM (several state sites block non-US IPs):

    python -m torehancast.feedcheck

Reports HTTP status, content type, size, and whether a bot-challenge page came
back instead of data. A challenge is reported, never worked around.
"""

from __future__ import annotations

import httpx

from .http import USER_AGENT

CHECKS: dict[str, list[str]] = {
    "GA": [
        "https://results.sos.ga.gov/results/public/api/elections/Georgia/2024NovGen/data",
        "https://results.sos.ga.gov/results/public/api/elections/Georgia/2026NovGen/data",
    ],
    "NC": ["https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2024_11_05/results_pct_20241105.zip"],
    "FL": ["https://results.elections.myflorida.com/downloadresults.asp?ElectionDate=11/5/2024&DATAMODE="],
    "TX": ["https://results.texas-election.com/static/data/ElectionConstants_404.json"],
    "OH": ["https://liveresults.ohiosos.gov/", "https://www.ohiosos.gov/elections/election-results-and-data/"],
    "IA": ["https://electionresults.iowa.gov/IA/122322/current_ver.txt"],
    "KS": ["https://ent.sos.ks.gov/national.html", "https://sos.ks.gov/elections/election-results.html"],
    "SC": ["https://www.enr-scvotes.org/SC/122436/current_ver.txt"],
    "MI": [
        "https://mielections.us/",
        "https://www.michigan.gov/sos/elections/election-results-and-data",
        "https://miboecfr.nictusa.com/cfr/presults/2024GEN.zip",
    ],
    # Directory listings are refused (IIS 403); individual files are served.
    "MN": ["https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt"],
    "ME": ["https://www.maine.gov/sos/cec/elec/results/index.html"],
    "AK": ["https://www.elections.alaska.gov/election-results/", "https://www.elections.alaska.gov/results/24GENR/"],
    # Resolves only from US networks.
    "NE": ["https://electionresults.nebraska.gov/"],
}

CHALLENGE_MARKERS = ("cf-chl", "Just a moment...", "challenge-platform", "security check", "Attention Required!")


def check(url: str, client: httpx.Client) -> str:
    try:
        r = client.get(url)
    except httpx.HTTPError as exc:
        return f"ERROR {type(exc).__name__}: {exc}"
    head = r.text[:4000] if "text" in r.headers.get("content-type", "") else ""
    challenged = r.headers.get("cf-mitigated") == "challenge" or any(m in head for m in CHALLENGE_MARKERS)
    return (
        f"{r.status_code} {r.headers.get('content-type', '?').split(';')[0]} {len(r.content):,} bytes"
        + ("  ⚠ BOT CHALLENGE" if challenged else "")
    )


def main() -> None:
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        for state, urls in CHECKS.items():
            for url in urls:
                print(f"{state}  {check(url, client):45s}  {url}")


if __name__ == "__main__":
    main()
