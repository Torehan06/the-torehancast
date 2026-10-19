"""Model output → the JSON the dashboard reads.

Two rules shape every payload:

1. **Priors stay private.** The hand-entered priors (margin ± sd, expected turnout)
   must not be recoverable by site visitors, including through devtools. So until a
   live state has reported votes, its JSON says only "waiting": no probabilities,
   margins, intervals, expected votes or anything else derived from the prior.
   Optionally (`gate: data_weight`), a state is held back until the data carries at
   least 3× the prior's weight on the statewide swing. Replays are published in full;
   their priors are about past elections.
2. **Small and cacheable.** One summary file for the front page, one detail file per
   state (county table), written atomically with a short Cache-Control.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .model.simulate import RaceModel, Result

WAITING = "waiting"
LIVE = "live"
GATES = ("first_votes", "data_weight")
DATA_WEIGHT_RELEASE = 3.0  # data precision ≥ 3× prior precision
CACHE_CONTROL = "public, max-age=20"


@dataclass(frozen=True)
class StateUpdate:
    state: str
    race: str
    candidates: dict[str, str]  # side → display name, e.g. {"D": "Ossoff", "R": "..."}
    result: Result
    model: RaceModel
    as_of: str | None


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


def state_summary(update: StateUpdate, mode: str, gate: str = "first_votes") -> dict:
    base = {"state": update.state, "race": update.race, "as_of": update.as_of}
    if not released(update, mode, gate):
        return {**base, "status": WAITING}  # nothing derived from the prior, by design
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
    }


def state_detail(update: StateUpdate, mode: str, gate: str = "first_votes") -> dict:
    summary = state_summary(update, mode, gate)
    if summary["status"] == WAITING:
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


def publish(updates: list[StateUpdate], writer, mode: str, gate: str = "first_votes") -> None:
    if mode not in ("live", "replay") or gate not in GATES:
        raise ValueError(f"mode={mode!r} gate={gate!r}")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for u in updates:
        writer.write(f"data/{mode}/{u.state}.json", state_detail(u, mode, gate))
    writer.write(
        f"data/{mode}/summary.json",
        {"generated_at": now, "mode": mode, "states": [state_summary(u, mode, gate) for u in updates]},
    )
