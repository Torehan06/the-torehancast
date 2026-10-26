"""Model output → the JSON the dashboard reads.

Two rules shape every payload:

1. **Priors stay private.** The hand-entered priors (margin ± sd, expected turnout)
   must not be recoverable by site visitors, including through devtools. So until a
   live state has reported votes, its JSON says only "waiting": no probabilities,
   margins, intervals, expected votes or anything else derived from the prior.
   Optionally (`gate: data_weight`), a state is held back until the data carries at
   least 3× the prior's weight on the statewide swing. Replays are published in full;
   their priors are about past elections.
2. **Small and cacheable.** `summary.json` (Senate) and `house.json` for the page, one
   detail file per modeled race (`races/{race_id}.json`, county table), written
   atomically with a short Cache-Control.

Every entry names its race (`race`, the canonical ID from districts.py), `race_type`
and `district` (null for Senate races).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import posixpath
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import districts
from .model.rcv import RCVResult
from .model.simulate import RaceModel, Result

WAITING = "waiting"
LIVE = "live"
GATES = ("first_votes", "data_weight")
DATA_WEIGHT_RELEASE = 3.0  # data precision ≥ 3× prior precision
CACHE_CONTROL = "public, max-age=20"
UPLOAD_WORKERS = 8


@dataclass(frozen=True)
class StateUpdate:
    state: str
    race: str  # canonical race ID, e.g. "2026-NC-SEN", "2026-AK-HAL"
    candidates: dict[str, str]  # side → display name, e.g. {"D": "Ossoff", "R": "..."}
    result: Result
    model: RaceModel
    as_of: str | None
    rcv: RCVResult | None = None
    # Observed counts from the feed, every key the adapter produced (pooled "other"
    # included), e.g. Snapshot.totals(). Published as `votes` for the display
    # candidates; `vote_share` divides by all of them. None: not published.
    votes: dict[str, int] | None = None
    # From the race config. Keyword-only and required: an RCV race published without
    # its flag would show plurality probabilities, so there is no default.
    race_type: str = field(kw_only=True)
    district: int | None = field(kw_only=True)
    ranked_choice: bool = field(kw_only=True)


@dataclass(frozen=True)
class ResultsOnlyUpdate:
    """Observed statewide results; no model, prior, or simulation required.

    Candidate keys must include every reported option (including independents).
    pct_reporting is the feed's fraction of units reporting, never a turnout
    projection. Use None when the source does not supply it.
    """

    state: str
    race: str
    candidates: dict[str, str]
    votes: dict[str, int]
    pct_reporting: float | None
    as_of: str | None
    race_type: str = field(kw_only=True)
    district: int | None = field(kw_only=True)
    # False: the contest isn't in the feed yet. It has no candidates or votes and
    # publishes as waiting; otherwise empty candidates are an error.
    in_feed: bool = field(default=True, kw_only=True)

    def validate(self) -> None:
        if not self.in_feed:
            if self.candidates or self.votes or self.pct_reporting is not None:
                raise ValueError("a contest not in the feed has no candidates, votes or reporting")
            return
        if not self.candidates or self.votes.keys() != self.candidates.keys():
            raise ValueError("reported vote keys must match display candidates exactly")
        if any(not isinstance(k, str) or not k or not isinstance(v, str)
               for k, v in self.candidates.items()):
            raise ValueError("candidate identifiers and names must be strings")
        if any(type(v) is not int or v < 0 for v in self.votes.values()):
            raise ValueError("reported votes must be nonnegative integers")
        if self.pct_reporting is not None and (
            type(self.pct_reporting) not in (int, float)
            or not math.isfinite(self.pct_reporting) or not 0 <= self.pct_reporting <= 1
        ):
            raise ValueError("reporting fraction must be between zero and one or None")


Update = StateUpdate | ResultsOnlyUpdate


def _check_identity(update: Update) -> None:
    """The race ID, type, district and state must agree, as districts.py defines them."""
    if districts.race_identity(update.race) != (update.state, update.race_type, update.district):
        raise ValueError(f"{update.race}: race ID, race_type, district and state disagree")


def _is_rcv(update: StateUpdate) -> bool:
    # config.py requires ranked_choice for every ME and AK federal race, so these
    # fail closed (awaiting_first_choices) before their RCV draws exist.
    return update.ranked_choice or update.rcv is not None


def released(update: StateUpdate, mode: str, gate: str = "first_votes") -> bool:
    if mode == "replay":
        return True
    if update.result.reported_votes <= 0:
        return False
    if gate == "data_weight":
        return update.model.last_data_weight >= DATA_WEIGHT_RELEASE
    return True


def _round(x: float, digits: int = 4) -> float:
    return float(round(x, digits))


def _reported(update: StateUpdate) -> dict:
    """`votes` and `vote_share` for a released modeled race (observed counts only)."""
    if update.votes is None:
        return {}
    if any(type(v) is not int or v < 0 for v in update.votes.values()):
        raise ValueError("reported votes must be nonnegative integers")
    total = sum(update.votes.values())
    # An empty count has no keys at all; once votes exist, a missing display
    # candidate means the adapter and the race config disagree.
    if total and (missing := set(update.candidates) - set(update.votes)):
        raise ValueError(f"reported votes lack display candidates: {sorted(missing)}")
    votes = {k: update.votes.get(k, 0) for k in update.candidates}
    return {"votes": votes, "vote_share": {k: _round(v / total) if total else 0.0 for k, v in votes.items()}}


def state_summary(update: Update, mode: str, gate: str = "first_votes") -> dict:
    _check_identity(update)
    base = {"state": update.state, "race": update.race, "race_type": update.race_type,
            "district": update.district, "as_of": update.as_of,
            "modeled": isinstance(update, StateUpdate)}
    if isinstance(update, ResultsOnlyUpdate):
        update.validate()
        total = sum(update.votes.values())
        if total == 0:
            return {**base, "status": WAITING}
        return {
            **base, "status": LIVE, "candidates": update.candidates,
            "votes": update.votes,
            "vote_share": {k: v / total for k, v in update.votes.items()},
            "pct_reporting": update.pct_reporting,
        }
    if not released(update, mode, gate):
        return {**base, "status": WAITING}  # nothing derived from the prior, by design
    if _is_rcv(update):
        if update.rcv is None:
            unknown = dict.fromkeys(update.candidates)
            return {
                **base, "status": LIVE, "candidates": update.candidates,
                "rcv_status": "awaiting_first_choices",
                "p_outright": unknown, "p_via_rcv": unknown, "p_win": unknown,
                "p_no_rcv_needed": None, **_reported(update),
            }
        rcv = update.rcv
        if set(rcv.p_win) != set(update.candidates):
            raise ValueError("RCV output candidates must match display candidates exactly")
        # Do not round components independently: P(win) must remain their sum.
        return {
            **base, "status": LIVE, "candidates": update.candidates,
            "rcv_status": rcv.status,
            "p_outright": rcv.p_outright, "p_via_rcv": rcv.p_via_rcv,
            "p_win": rcv.p_win, "p_no_rcv_needed": rcv.p_no_rcv_needed, **_reported(update),
        }
    r = update.result
    return {
        **base,
        "status": LIVE,
        "candidates": update.candidates,
        "p_win": {k: _round(v, 3) for k, v in r.p_win.items()},
        "margin": {
            "median": _round(r.margin_median),
            "p80": [_round(x) for x in r.margin_80],
            "p95": [_round(x) for x in r.margin_95],
        },
        "reported_votes": r.reported_votes,
        "expected_votes": int(round(r.expected_votes)),
        "share_counted": _round(r.share_counted, 3),
        **_reported(update),
    }


def state_detail(update: Update, mode: str, gate: str = "first_votes") -> dict:
    summary = state_summary(update, mode, gate)
    if isinstance(update, ResultsOnlyUpdate) or summary["status"] == WAITING or _is_rcv(update):
        return summary
    counties = update.model.last_counties
    summary["counties"] = [
        {
            "id": row.unit_id,
            "status": row.status,
            "reported_votes": int(row.reported_votes),
            "reported_margin": _round(row.reported_margin) if row.reported_votes else None,
            "counted_share": _round(min(row.counted_share, 1.0), 3),
            "expected_margin": _round(row.expected_margin),
        }
        for row in counties.itertuples()
    ]
    return summary


def _json_default(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    raise TypeError(type(x))


class LocalWriter:
    """Writes into a directory (for local preview and tests), atomically."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def write(self, key: str, payload: dict) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp") as f:
            json.dump(payload, f, default=_json_default, separators=(",", ":"))
        os.replace(f.name, path)


class S3Writer:
    """Writes to the public site bucket under data/. Config lives in a separate bucket."""

    def __init__(self, bucket: str, client=None):
        import boto3

        self.bucket = bucket
        self.s3 = client or boto3.client("s3")

    def write(self, key: str, payload: dict) -> None:
        if not key.startswith("data/"):
            raise ValueError(f"refusing to publish outside data/: {key}")
        body = json.dumps(payload, default=_json_default, separators=(",", ":")).encode()
        self.s3.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType="application/json", CacheControl=CACHE_CONTROL
        )


class GCSWriter:
    """Writes to the public Google Cloud Storage data bucket, under data/ only.

    The bucket's public role can't be scoped to a prefix, so this check is what keeps
    it holding nothing but data/: any other key is refused before an upload starts.
    Bodies are gzipped (browsers decompress them; GCS decompresses for clients that
    don't accept gzip), and a file whose body hasn't changed since this writer last
    uploaded it is skipped, so an unchanged race costs no upload.
    """

    def __init__(self, bucket: str, client=None):
        if client is None:
            from google.cloud import storage

            client = storage.Client()
        self.bucket = client.bucket(bucket)
        self._uploaded: dict[str, str] = {}  # key → sha256 of the last body uploaded

    def write(self, key: str, payload: dict) -> None:
        if not key.startswith("data/") or posixpath.normpath(key) != key:
            raise ValueError(f"refusing to publish outside data/: {key}")
        body = json.dumps(payload, default=_json_default, separators=(",", ":")).encode()
        digest = hashlib.sha256(body).hexdigest()
        if self._uploaded.get(key) == digest:
            return
        blob = self.bucket.blob(key)
        blob.cache_control = CACHE_CONTROL
        blob.content_encoding = "gzip"
        blob.upload_from_string(gzip.compress(body, mtime=0), content_type="application/json")
        self._uploaded[key] = digest

    def write_many(self, items: list[tuple[str, dict]]) -> None:
        """Upload in parallel; every item is attempted, then the first failure is raised."""
        for key, _ in items:  # refuse the whole batch before any upload starts
            if not key.startswith("data/") or posixpath.normpath(key) != key:
                raise ValueError(f"refusing to publish outside data/: {key}")
        with ThreadPoolExecutor(UPLOAD_WORKERS) as pool:
            futures = [pool.submit(self.write, key, payload) for key, payload in items]
        for future in futures:
            future.result()


def _write_all(writer, items: list[tuple[str, dict]]) -> None:
    if hasattr(writer, "write_many"):
        writer.write_many(items)
    else:
        for key, payload in items:
            writer.write(key, payload)


def publish(updates: list[Update], writer, mode: str, gate: str = "first_votes") -> None:
    """Detail files for modeled races, then summary.json (Senate) and house.json.

    A list with no Senate (or no House) races leaves that file untouched: an empty
    list is invalid public JSON, and the page keeps showing the last good one.
    """
    if mode not in ("live", "replay") or gate not in GATES:
        raise ValueError(f"mode={mode!r} gate={gate!r}")
    if len({u.race for u in updates}) != len(updates):
        raise ValueError("one update per race")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_all(writer, [(f"data/{mode}/races/{u.race}.json", state_detail(u, mode, gate))
                        for u in updates if isinstance(u, StateUpdate)])
    senate = [state_summary(u, mode, gate) for u in updates if u.race_type != "house"]
    house = [state_summary(u, mode, gate) for u in updates if u.race_type == "house"]
    if senate:
        writer.write(f"data/{mode}/summary.json", {"generated_at": now, "mode": mode, "states": senate})
    if house:
        writer.write(f"data/{mode}/house.json", {"generated_at": now, "mode": mode, "races": house})
