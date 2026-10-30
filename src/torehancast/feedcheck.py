"""Can this machine reach each state's official results feed?

Run from the US poller VM (several state sites block non-US IPs):

    python -m torehancast.feedcheck                # every URL below, then config's
    python -m torehancast.feedcheck --contests GA  # parse a state's results-only sources

Reports HTTP status, content type, size, and whether a bot-challenge page came
back instead of data. A challenge is reported, never worked around.

`--contests ST` downloads each of the state's results-only sources once, the way
the poller does, and prints which configured contests the document holds (expected
vs found districts), their candidates by side key, votes and reporting.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx

from . import config
from .adapters import get as get_adapter
from .http import USER_AGENT, PoliteClient, ssl_context

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
    # The server sends the wrong intermediate; http.EXTRA_CAS supplies the right one.
    "AK": [
        "https://www.elections.alaska.gov/election-results/",
        "https://www.elections.alaska.gov/results/24GENR/ENRbyPrecinct.csv",
        "https://www.elections.alaska.gov/enr26/results/GA_ENR_Precinct_State_of_Alaska.csv",
    ],
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


def config_urls(directory: Path = config.DEFAULT_CONFIG_DIR) -> dict[str, list[str]]:
    """Every feed and reference URL in config, by state, minus those CHECKS already has.

    New results-only sources are checked without editing this file.
    """
    settings = config.load_config(directory)
    feeds = [(race.state, settings.feeds[race_id]) for race_id, race in settings.races.items()
             if race_id in settings.feeds]
    try:
        results = config.load_results(settings, directory)
        feeds += [(source.state, source.feed) for source in results.sources.values()]
    except config.ConfigError as exc:
        print(f"results config not loaded: {exc}")
    known = {url for urls in CHECKS.values() for url in urls}
    out: dict[str, list[str]] = {}
    for state, feed in feeds:
        for url in (feed.url, feed.reference_url):
            if url and url not in known and url not in out.get(state, []):
                out.setdefault(state, []).append(url)
    return out


def contests_report(state: str, directory: Path = config.DEFAULT_CONFIG_DIR, client=None,
                    adapter=get_adapter) -> list[str]:
    """Lines describing what each of `state`'s results-only sources holds right now."""
    results = config.load_results(config.load_config(directory), directory)
    sources = {name: s for name, s in results.sources.items() if s.state == state}
    if not sources:
        return [f"{state}: no results-only sources in config/results/{state}.yaml"]
    lines = []
    for name, source in sources.items():
        feed = source.feed
        contests = [c for c in results.contests.values() if c.source == name]
        lines.append(f"{name}  status={source.status} adapter={feed.adapter} url={feed.url}")
        if not feed.adapter:
            lines.append("  no adapter configured")
            continue
        try:
            module = adapter(feed.adapter)
            parse_all = getattr(module, "parse_all_contests")
            found = parse_all(module.fetch_source(client or PoliteClient(), feed), contests)
        except Exception as exc:  # report and move on to the next source
            lines.append(f"  could not read: {type(exc).__name__}: {exc}")
            continue
        unverified = [c.race_id for c in contests if not c.contest]
        missing = [c.race_id for c in contests if c.contest and c.race_id not in found]
        lines.append(f"  expected {len(contests)}, found {len(found)}"
                     + (f"; missing {', '.join(missing)}" if missing else "")
                     + (f"; no template {', '.join(unverified)}" if unverified else ""))
        for c in contests:
            totals = found.get(c.race_id)
            if totals is None:
                continue
            reporting = "?" if totals.pct_reporting is None else f"{totals.pct_reporting:.0%}"
            people = "; ".join(f"{side} {totals.candidates[side]} {totals.votes[side]:,}" for side in totals.votes)
            lines.append(f"  {c.race_id}  {reporting} reporting  {people}")
    return lines


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contests", metavar="ST", help="parse the state's results-only sources")
    args = parser.parse_args(argv)
    if args.contests:
        for line in contests_report(args.contests.upper()):
            print(line)
        return
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}, verify=ssl_context()) as client:
        for state, urls in CHECKS.items():
            for url in urls:
                print(f"{state}  {check(url, client):45s}  {url}")
        for state, urls in config_urls().items():
            for url in urls:
                print(f"{state}  {check(url, client):45s}  {url}")


if __name__ == "__main__":
    main()
