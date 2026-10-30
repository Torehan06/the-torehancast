"""Any state on Clarity ENR, for results-only sources that need config only (W4b).

`url` in config is the state's Clarity root, e.g.
`https://results.enr.clarityelections.com/CO`, and `election_id` the election, so
the files are the same two as South Carolina's:

    {url}/{election_id}/current_ver.txt
    {url}/{election_id}/{version}/reports/detailxml.zip

Modeled races keep their own state adapter (`sc_clarity`, `ia_clarity`); this one
serves results-only contests and has no model input to offer.
"""

from __future__ import annotations

from ..http import PoliteClient
from . import sc_clarity

parse_all_contests = sc_clarity.parse_all_contests


def fetch_source(client: PoliteClient, feed) -> str:
    if not feed.url or not feed.election_id:
        raise ValueError("a Clarity source needs its state root url and election_id")
    return sc_clarity.fetch(client, feed.election_id, base=feed.url.rstrip("/"))


def parse(document, contest, cmap, race):
    raise NotImplementedError("the generic Clarity adapter serves results-only sources; use the state's adapter")


def final_snapshot(spec, archives, cmap, key):
    raise NotImplementedError("the generic Clarity adapter has no archived replay; use the state's adapter")
