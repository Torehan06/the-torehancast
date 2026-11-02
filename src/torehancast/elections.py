"""Historical elections: config lookup, archive → final Snapshot → baseline table."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from . import adapters
from .candidates import CandidateMap
from .schema import Snapshot

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
ARCHIVES = ROOT / "data" / "archives"
BASELINES = ROOT / "data" / "baselines"


@dataclass(frozen=True)
class Election:
    state: str
    key: str  # e.g. "2022_sen"
    adapter: str
    spec: dict

    @property
    def candidates(self) -> CandidateMap:
        return CandidateMap(self.spec["candidates"])


def specs(state: str) -> dict[str, dict]:
    """A state's historical elections: elections.yaml plus its House file, config/house/<ST>.yaml.

    House files keep one state's House baselines out of the shared file, so per-state
    sessions don't edit the same YAML. A key may live in only one of the two.
    """
    shared = yaml.safe_load((CONFIG / "elections.yaml").read_text()).get(state) or {}
    house_file = CONFIG / "house" / f"{state}.yaml"
    house = yaml.safe_load(house_file.read_text())["elections"] if house_file.exists() else {}
    if clash := shared.keys() & house.keys():
        raise ValueError(f"{state}: {sorted(clash)} defined in both elections.yaml and house/{state}.yaml")
    return shared | house


def load(state: str, key: str) -> Election:
    spec = specs(state)[key]
    return Election(state, key, spec["adapter"], spec)


def final_snapshot(election: Election) -> Snapshot:
    """The certified final result, parsed from the archived official files."""
    adapter = adapters.get(election.adapter)
    snap = adapter.final_snapshot(election.spec, ARCHIVES / election.state, election.candidates, election.key)
    if not snap.cells:
        raise ValueError(f"{election.state} {election.key}: contest not found in archive")
    return snap


def to_frame(snap: Snapshot, sides: tuple[str, ...] = ("D", "R", "other")) -> pd.DataFrame:
    """One row per (unit, vote type), one column per side."""
    rows = [
        {"unit_id": c.unit_id, "vote_type": c.vote_type, **{s: c.votes.get(s, 0) for s in sides}}
        for c in snap.cells
    ]
    return pd.DataFrame(rows).sort_values(["unit_id", "vote_type"]).reset_index(drop=True)


def baseline_path(state: str, key: str) -> Path:
    return BASELINES / f"{state}_{key}.csv"


def build_baseline(state: str, key: str) -> pd.DataFrame:
    df = to_frame(final_snapshot(load(state, key)))
    BASELINES.mkdir(parents=True, exist_ok=True)
    df.to_csv(baseline_path(state, key), index=False)
    return df


def read_baseline(state: str, key: str) -> pd.DataFrame:
    return pd.read_csv(baseline_path(state, key), dtype={"unit_id": str})
