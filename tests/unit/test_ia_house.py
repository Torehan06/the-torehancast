"""2026-IA-H01..H03: Iowa's House districts on the Senate's Clarity feed (W7).

The fixture is the real certified 2024 statewide detail.xml (EID 122322), the file
the baselines are built from, cut to the District 1–3 contests. No archives or
network needed.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import pandas as pd
import pytest
import yaml

from torehancast import demographics, elections, poller, publish
from torehancast.adapters import ia_clarity as ia
from torehancast.candidates import CandidateMap
from torehancast.replay import harness, units

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "ia" / "house"
DISTRICTS = {1: 20, 2: 22, 3: 21}  # county count
# Certified 2024 two-party totals (D, R) from the fixture.
TOTALS = {1: (206_156, 206_955), 2: (169_740, 233_340), 3: (197_962, 213_746)}


def race(d: int) -> str:
    return f"2026-IA-H{d:02d}"


def contest(d: int):
    spec = elections.load("IA", f"2024_house_{d:02d}").spec
    snap = ia.parse(ia.load_archive(FIX, "122322"), spec["contest"], CandidateMap(spec["candidates"]), race(d))
    return spec, snap


@pytest.mark.parametrize("d", DISTRICTS)
def test_each_district_contest_parses_with_both_sides(d):
    spec, snap = contest(d)
    assert len(snap.units()) == DISTRICTS[d]
    assert {c.vote_type for c in snap.cells} == {"early", "election_day"}
    totals = snap.totals()
    assert (totals["D"], totals["R"]) == TOTALS[d]
    assert set(snap.unit_reporting) == snap.units()


def test_districts_are_disjoint_whole_counties():
    sets = [contest(d)[1].units() for d in DISTRICTS]
    assert len(set().union(*sets)) == sum(len(s) for s in sets) == 63
    assert set().union(*sets) <= set(demographics.load("IA").unit_id)


@pytest.mark.parametrize("d", DISTRICTS)
def test_committed_baseline_is_the_fixture_contest(d):
    _, snap = contest(d)
    committed = elections.read_baseline("IA", f"2024_house_{d:02d}")
    pd.testing.assert_frame_equal(committed, elections.to_frame(snap), check_dtype=False)


@pytest.mark.parametrize("d", DISTRICTS)
def test_baseline_feed_and_demographics_share_one_unit_set(d):
    key = race(d)
    base = harness.race_baseline(key, f"2024_house_{d:02d}")
    feed = harness.to_race_units(key, contest(d)[1])
    demo = harness.make_model(key, f"2024_house_{d:02d}", ("2020_pres", "2024_pres"),
                              harness.RacePrior(0.0, 0.08, 0.75, 0.12)).demographics
    assert set(base.unit_id) == feed.units() == set(demo.unit_id)
    assert all(u.endswith(f"|{d:02d}") for u in feed.units())
    assert feed.unit_reporting.keys() == feed.units()


def test_replay_pair_is_restricted_to_the_district():
    key = race(1)
    spec = harness.replay_config(key)["primary"]
    keep = harness.replay_units(key, spec)
    assert len(keep) == 20 and "SCOTT|01" in keep
    model, _ = harness.build_model(key)
    assert set(model.baseline.unit_id) == keep


# -- live: one poller cycle for IA-1 --------------------------------------------------

AFTER = datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)  # 9 pm CT; Iowa closes at 8
TEST_PRIOR = {"margin": 0.0, "margin_sd": 0.08, "turnout_ratio": 0.75, "turnout_sd": 0.12}  # synthetic


class Feed:
    def __init__(self, snap):
        self.snap = snap

    def fetch_source(self, client, feed):
        return "document"

    def parse(self, document, contest, cmap, race):
        return self.snap


def test_poller_models_a_district_from_its_own_baseline(tmp_path):
    spec, snap = contest(1)
    config = tmp_path / "config"
    config.mkdir()
    for name in ("races.yaml", "feeds.yaml", "priors.example.yaml"):
        shutil.copy(ROOT / "config" / name, config / name)
    feeds = yaml.safe_load((config / "feeds.yaml").read_text())
    feeds["feeds"][race(1)].update(
        status="ready", url="https://example.test/ia", election_id="test", contest=spec["contest"],
        candidates=spec["candidates"], display={"D": "Christina Bohannan", "R": "Mariannette Miller-Meeks"})
    (config / "feeds.yaml").write_text(yaml.safe_dump(feeds))
    priors = yaml.safe_load((config / "priors.example.yaml").read_text())
    priors["priors"][race(1)] = TEST_PRIOR
    (config / "priors.yaml").write_text(yaml.safe_dump(priors))

    p = poller.Poller(publish.LocalWriter(tmp_path / "out"), config, adapter=lambda name: Feed(snap),
                      clock=lambda: AFTER, n_draws=500)
    p.cycle()
    model = p._races[race(1)].model
    assert set(model.baseline.unit_id) == {units.county_part(u, 1) for u in snap.units()}
    house = {r["race"]: r for r in json.loads((tmp_path / "out/data/live/house.json").read_text())["races"]}
    published = house[race(1)]
    assert published["status"] == "live" and published["modeled"] is True
    assert published["votes"] == {"D": TOTALS[1][0], "R": TOTALS[1][1]}
    detail = json.loads((tmp_path / f"out/data/live/races/{race(1)}.json").read_text())
    assert "reported cell not in baseline" not in json.dumps(detail)
