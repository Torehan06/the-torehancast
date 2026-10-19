"""Historical elections: config lookup, archive → final Snapshot → baseline table."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

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


def load(state: str, key: str) -> Election:
    spec = yaml.safe_load((CONFIG / "elections.yaml").read_text())[state][key]
    return Election(state, key, spec["adapter"], spec)


def final_snapshot(election: Election) -> Snapshot:
    """The certified final result, parsed from the archived official files."""
    if election.adapter == "ga_enhanced_voting":
        from .adapters import ga_enhanced_voting as ga

        docs = ga.load_archive(ARCHIVES / "GA" / election.spec["code"])
        cmap = election.candidates
        snap = ga.snapshot_from_docs(docs, election.spec["contest"], cmap, election.key)
    elif election.adapter == "nc_sbe":
        from .adapters import nc_sbe

        text = nc_sbe.load_archive(ARCHIVES / "NC", election.spec["date"])
        snap = nc_sbe.parse(text, election.spec["contest"], election.candidates, election.key)
    elif election.adapter == "fl_dos":
        from .adapters import fl_dos

        text = fl_dos.load_archive(ARCHIVES / "FL", election.spec["date"])
        snap = fl_dos.parse(text, election.spec["race_code"], election.candidates, election.key)
    elif election.adapter == "sc_clarity":
        from .adapters import sc_clarity

        text = sc_clarity.load_archive(ARCHIVES / "SC", election.spec["election_id"])
        snap = sc_clarity.parse(text, election.spec["contest"], election.candidates, election.key)
    else:
        raise NotImplementedError(election.adapter)
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
