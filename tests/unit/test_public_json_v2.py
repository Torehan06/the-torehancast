"""Contract v2: summary.json (Senate), house.json, races/{race_id}.json, and the value scan
at election-night scale (76 private priors, every federal race published)."""

import copy
import json
import random
from dataclasses import replace

import pandas as pd
import pytest
import yaml

from torehancast import config, districts, public_json, publish
from torehancast.model.composition import CompositionPrior
from torehancast.model.simulate import RaceModel, RacePrior
from torehancast.model.tau import HistoricalParams
from torehancast.schema import ALL, Cell, Snapshot

NOW = "2026-11-04T02:14:05+00:00"


# Publisher ------------------------------------------------------------------

@pytest.fixture(scope="module")
def result_and_model():
    baseline = pd.DataFrame([{"unit_id": "A", "vote_type": ALL, "D": 490, "R": 450}])
    params = HistoricalParams(0.04, 0.08, 0.03, 0.05, CompositionPrior(0.2, 0.1, 0.1, 0.05), 1000)
    model = RaceModel(baseline, RacePrior(0, 0.1, 1, 0.1), params)
    snap = Snapshot("NC", "x", "now", [Cell("A", ALL, {"D": 490, "R": 450})])
    return model.run(snap, n_draws=100, seed=0), model


def modeled(result_and_model, race_id, **changes):
    state, race_type, district = districts.race_identity(race_id)
    result, model = result_and_model
    fields = dict(race_type=race_type, district=district, ranked_choice=state in ("ME", "AK"))
    return publish.StateUpdate(state, race_id, {"D": "Dem", "R": "Rep"}, result, model, "now",
                               votes={"D": 490, "R": 450}, **(fields | changes))


def results_only(race_id, **changes):
    state, race_type, district = districts.race_identity(race_id)
    fields = dict(candidates={"D": "Dem", "R": "Rep"}, votes={"D": 60, "R": 40}, pct_reporting=0.5,
                  as_of="now", race_type=race_type, district=district)
    return publish.ResultsOnlyUpdate(state, race_id, **(fields | changes))


def test_senate_and_house_go_to_separate_files(result_and_model, tmp_path):
    updates = [modeled(result_and_model, "2026-NC-SEN"), modeled(result_and_model, "2026-NC-H01"),
               results_only("2026-NC-H02"), results_only("2026-VA-SEN")]
    publish.publish(updates, publish.LocalWriter(tmp_path), "replay")
    root = tmp_path / "data/replay"
    summary = json.loads((root / "summary.json").read_text())
    house = json.loads((root / "house.json").read_text())
    assert [r["race"] for r in summary["states"]] == ["2026-NC-SEN", "2026-VA-SEN"]
    assert [r["race"] for r in house["races"]] == ["2026-NC-H01", "2026-NC-H02"]
    assert house["races"][0]["district"] == 1 and house["races"][0]["race_type"] == "house"
    assert sorted(p.name for p in (root / "races").iterdir()) == ["2026-NC-H01.json", "2026-NC-SEN.json"]
    assert not list(root.glob("NC.json"))
    assert public_json.check_tree(tmp_path).files == 4


def test_a_cycle_without_house_races_leaves_house_json_alone(result_and_model, tmp_path):
    publish.publish([modeled(result_and_model, "2026-NC-SEN")], publish.LocalWriter(tmp_path), "replay")
    assert not (tmp_path / "data/replay/house.json").exists()
    publish.publish([results_only("2026-NC-H02")], publish.LocalWriter(tmp_path), "replay")
    assert (tmp_path / "data/replay/house.json").exists()


@pytest.mark.parametrize("change", [
    dict(race="2026-NC-H15"),  # no such district
    dict(race="2026-NC-H02"),  # district says 1
    dict(district=None),
    dict(race_type="senate"),
    dict(state="SC"),
])
def test_identity_fields_must_agree(result_and_model, change):
    update = replace(modeled(result_and_model, "2026-NC-H01"), **change)
    with pytest.raises(ValueError, match="disagree"):
        publish.state_summary(update, "replay")


def test_one_update_per_race(result_and_model, tmp_path):
    update = modeled(result_and_model, "2026-NC-SEN")
    with pytest.raises(ValueError, match="one update per race"):
        publish.publish([update, update], publish.LocalWriter(tmp_path), "replay")


def test_ranked_choice_comes_from_config_so_ak_house_fails_closed(result_and_model):
    out = publish.state_summary(modeled(result_and_model, "2026-AK-HAL"), "live")
    assert out["rcv_status"] == "awaiting_first_choices" and out["p_win"] == {"D": None, "R": None}
    plain = publish.state_summary(modeled(result_and_model, "2026-NC-H01"), "live")
    assert "rcv_status" not in plain and plain["p_win"]["D"] is not None


def test_config_requires_ranked_choice_for_me_and_ak(tmp_path):
    from shutil import copy as copy_file
    for name in ("races.yaml", "feeds.yaml", "priors.example.yaml"):
        copy_file(config.DEFAULT_CONFIG_DIR / name, tmp_path / name)
    doc = yaml.safe_load((tmp_path / "races.yaml").read_text())
    doc["races"]["2026-AK-HAL"]["ranked_choice"] = False
    (tmp_path / "races.yaml").write_text(yaml.safe_dump(doc))
    with pytest.raises(config.ConfigError, match="ranked-choice"):
        config.load_config(tmp_path)


# Checker --------------------------------------------------------------------

def entry(race_id, rng=None, counties=3, **changes):
    rng = rng or random.Random(0)
    state, race_type, district = districts.race_identity(race_id)
    m = round(rng.uniform(-0.3, 0.3), 4)
    p = round(rng.random(), 3)
    value = {
        "state": state, "race": race_id, "race_type": race_type, "district": district,
        "as_of": "2026-11-03T21:14:00-05:00", "status": "live", "modeled": True,
        "candidates": {"D": "Dem", "R": "Rep"}, "p_win": {"D": p, "R": round(1 - p, 3)},
        "margin": {"median": m, "p80": [round(m - 0.04, 4), round(m + 0.04, 4)],
                   "p95": [round(m - 0.07, 4), round(m + 0.07, 4)]},
        "reported_votes": 1000, "expected_votes": 2000, "share_counted": round(rng.random(), 3),
        "votes": {"D": 520, "R": 480}, "vote_share": {"D": 0.52, "R": 0.48},
        "counties": [{"id": f"C{i}", "status": "complete", "reported_votes": 100 + i,
                      "reported_margin": round(rng.uniform(-0.6, 0.6), 4), "counted_share": 1.0,
                      "expected_margin": round(rng.uniform(-0.6, 0.6), 4)} for i in range(counties)],
    }
    return value | changes


def result_entry(race_id, rng):
    state, race_type, district = districts.race_identity(race_id)
    d, r = rng.randint(1, 90000), rng.randint(1, 90000)
    return {"state": state, "race": race_id, "race_type": race_type, "district": district,
            "as_of": "2026-11-03T21:14:00-05:00", "status": "live", "modeled": False,
            "candidates": {"D": "Dem", "R": "Rep"}, "votes": {"D": d, "R": r},
            "vote_share": {"D": d / (d + r), "R": r / (d + r)}, "pct_reporting": round(rng.random(), 3)}


def write_tree(root, entries):
    data = root / "data/live"
    (data / "races").mkdir(parents=True)
    senate = [e for e in entries if e["race_type"] != "house"]
    house = [e for e in entries if e["race_type"] == "house"]
    if senate:
        (data / "summary.json").write_text(json.dumps({"generated_at": NOW, "mode": "live", "states": senate}))
    if house:
        (data / "house.json").write_text(json.dumps({"generated_at": NOW, "mode": "live", "races": house}))
    for e in entries:
        if e["modeled"]:
            (data / f"races/{e['race']}.json").write_text(json.dumps(e))


def write_priors(path, priors):
    path.write_text(yaml.safe_dump({"priors": priors}))
    return path


def hand_entered(rng):
    """Priors written the way people write them: 1-3 decimals."""
    return {"margin": round(rng.uniform(-0.25, 0.25), rng.choice([2, 3])),
            "margin_sd": rng.choice([0.05, 0.06, 0.07, 0.08, 0.09, 0.1]),
            "turnout_ratio": round(rng.uniform(0.8, 1.15), rng.choice([1, 2])),
            "turnout_sd": rng.choice([0.1, 0.12, 0.15])}


@pytest.fixture(scope="module")
def night(tmp_path_factory):
    """Every federal race published live: 76 modeled with county tables, the rest results-only."""
    rng = random.Random(2026)
    modeled_ids = list(config.load_config(config.DEFAULT_CONFIG_DIR).races)
    assert len(modeled_ids) == 76
    priors = {race: hand_entered(rng) for race in modeled_ids}
    entries = []
    for race in districts.senate_race_ids() + districts.house_race_ids():
        if race in priors:
            entries.append(entry(race, rng, counties=95 if "-SEN" in race else 12))
        else:
            entries.append(result_entry(race, rng))
    return entries, priors


def test_a_whole_election_night_raises_no_false_alarm(night, tmp_path):
    entries, priors = night
    write_tree(tmp_path / "out", entries)
    report = public_json.check_tree(tmp_path / "out", priors=write_priors(tmp_path / "p.yaml", priors))
    assert report.files == 2 + 76 and report.private_values_checked


def test_hand_entered_values_really_do_appear_by_chance(night):
    # Why the precision floor exists: the old all-numbers scan would have failed this night.
    entries, priors = night
    tokens = {v for p in priors.values() for v in p.values()}
    published = {c["counted_share"] for e in entries if e["modeled"] for c in e["counties"]}
    published |= {e["p_win"]["D"] for e in entries if e["modeled"]}
    assert published & tokens


@pytest.mark.parametrize("where", ["candidate name", "as_of", "county id"])
def test_a_prior_written_into_text_is_caught_at_scale(night, tmp_path, where):
    entries, priors = night
    entries = copy.deepcopy(entries)
    race = "2026-IA-H02"
    target = next(e for e in entries if e["race"] == race)
    leaked = str(priors[race]["margin_sd"])
    if where == "candidate name":
        target["candidates"]["D"] = f"Dem {leaked}"
    elif where == "as_of":
        target["as_of"] = f"sd={leaked}"
    else:
        target["counties"][0]["id"] = f"C{leaked}"
    write_tree(tmp_path / "out", entries)
    with pytest.raises(public_json.PublicJSONError, match="private-value copy") as caught:
        public_json.check_tree(tmp_path / "out", priors=write_priors(tmp_path / "p.yaml", priors))
    assert leaked not in str(caught.value)


@pytest.mark.parametrize("field", ["median", "county"])
def test_a_precise_prior_copied_into_a_number_is_caught_at_scale(night, tmp_path, field):
    entries, priors = night
    entries, priors = copy.deepcopy(entries), copy.deepcopy(priors)
    race = "2026-PA-H07"
    priors[race]["margin"] = -0.0412873  # 7 decimals: a match can't be chance
    target = next(e for e in entries if e["race"] == race)
    if field == "median":
        m = round(priors[race]["margin"], 4)
        target["margin"] = {"median": m, "p80": [m - 0.04, m + 0.04], "p95": [m - 0.07, m + 0.07]}
    else:
        target["counties"][2]["expected_margin"] = priors[race]["margin"]
    write_tree(tmp_path / "out", entries)
    with pytest.raises(public_json.PublicJSONError, match="private-value copy"):
        public_json.check_tree(tmp_path / "out", priors=write_priors(tmp_path / "p.yaml", priors))


def test_a_precise_value_belonging_to_another_race_is_not_a_copy(night, tmp_path):
    entries, priors = night
    entries, priors = copy.deepcopy(entries), copy.deepcopy(priors)
    priors["2026-PA-H07"]["margin"] = -0.0412873
    next(e for e in entries if e["race"] == "2026-NC-SEN")["margin"]["median"] = -0.0413
    write_tree(tmp_path / "out", entries)
    public_json.check_tree(tmp_path / "out", priors=write_priors(tmp_path / "p.yaml", priors))


def test_identity_and_counts_are_not_mistaken_for_an_integer_prior(tmp_path):
    # turnout_ratio 1 would match district 1, a count of 1 and every ":01" in a timestamp.
    race = "2026-NC-H01"
    priors = {race: {"margin": -0.05, "margin_sd": 0.07, "turnout_ratio": 1, "turnout_sd": 0.1}}
    value = entry(race, votes={"D": 1, "R": 0}, vote_share={"D": 1.0, "R": 0.0}, as_of="2026-11-03T21:01:01-05:00")
    write_tree(tmp_path / "out", [value])
    public_json.check_tree(tmp_path / "out", priors=write_priors(tmp_path / "p.yaml", priors))


@pytest.mark.parametrize("problem", [
    "senate entry in house.json", "house entry in summary.json", "duplicate race",
    "file named for another race", "per-state file", "results-only detail file", "state disagrees",
])
def test_v2_layout_is_enforced(tmp_path, problem):
    nc_h01, nc_sen = entry("2026-NC-H01"), entry("2026-NC-SEN")
    write_tree(tmp_path, [nc_h01, nc_sen])
    data = tmp_path / "data/live"
    if problem == "senate entry in house.json":
        (data / "house.json").write_text(json.dumps({"generated_at": NOW, "mode": "live", "races": [nc_sen]}))
    elif problem == "house entry in summary.json":
        (data / "summary.json").write_text(json.dumps({"generated_at": NOW, "mode": "live", "states": [nc_h01]}))
    elif problem == "duplicate race":
        (data / "summary.json").write_text(json.dumps({"generated_at": NOW, "mode": "live", "states": [nc_sen, nc_sen]}))
    elif problem == "file named for another race":
        (data / "races/2026-NC-H02.json").write_text(json.dumps(nc_h01))
    elif problem == "per-state file":
        (data / "NC.json").write_text(json.dumps(nc_sen))
    elif problem == "results-only detail file":
        (data / "races/2026-NC-H02.json").write_text(json.dumps(result_entry("2026-NC-H02", random.Random(0))))
    else:
        (data / "races/2026-NC-SEN.json").write_text(json.dumps(nc_sen | {"state": "SC"}))
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path, mode="replay")
