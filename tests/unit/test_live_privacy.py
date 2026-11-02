"""Synthetic private canaries through the real model → live publisher → checker.

These are verification fixtures, never user-supplied live priors.
"""

import json
from dataclasses import asdict

import pandas as pd
import pytest
import yaml

from torehancast import public_json, publish
from torehancast.model.composition import CompositionPrior
from torehancast.model.simulate import RaceModel, RacePrior
from torehancast.model.tau import HistoricalParams
from torehancast.schema import ALL, Cell, Snapshot

CANARIES = [
    RacePrior(0.0234567, 0.0678912, 1.23456789, 0.143258),
    RacePrior(-0.0612345, 0.0890123, 0.9876543, 0.1765432),
]


def model(prior):
    baseline = pd.DataFrame([
        {"unit_id": u, "vote_type": ALL, "D": 500, "R": 500} for u in "ABCD"
    ])
    params = HistoricalParams(0.04, 0.08, 0.03, 0.05, CompositionPrior(0.2, 0.1, 0.1, 0.05), 1000)
    return RaceModel(baseline, prior, params)


def snapshot(state, stage):
    if stage == "empty":
        return Snapshot(state, "Senate", None, [])
    if stage == "thin":
        return Snapshot(state, "Senate", "now", [Cell("A", ALL, {"D": 3, "R": 2})],
                        unit_reporting={"A": 0.005})
    return Snapshot(state, "Senate", "now", [Cell(u, ALL, {"D": 600, "R": 400}) for u in "ABCD"],
                    cell_complete={(u, ALL): 1.0 for u in "ABCD"})


@pytest.mark.parametrize("prior", CANARIES)
@pytest.mark.parametrize("state", ["GA", "ME", "AK"])
@pytest.mark.parametrize("gate,stage,status", [
    ("first_votes", "empty", "waiting"), ("data_weight", "empty", "waiting"),
    ("data_weight", "thin", "waiting"), ("first_votes", "thin", "live"),
    ("data_weight", "final", "live"),
])
def test_live_pipeline_keeps_canary_inputs_private(tmp_path, prior, state, gate, stage, status, capsys):
    m = model(prior)
    snap = snapshot(state, stage)
    result = m.run(snap, n_draws=100, seed=7)
    if stage == "thin":
        assert m.last_data_weight < publish.DATA_WEIGHT_RELEASE
    elif stage == "final":
        assert m.last_data_weight >= publish.DATA_WEIGHT_RELEASE
    race = f"2026-{state}-SEN"
    update = publish.StateUpdate(state, race, {"D": "Dem", "R": "Rep"}, result, m, snap.as_of,
                                 race_type="senate", district=None, ranked_choice=state in ("ME", "AK"))
    out = tmp_path / "public"
    publish.publish([update], publish.LocalWriter(out), mode="live", gate=gate)
    private = tmp_path / "canary-private.yaml"
    private.write_text(yaml.safe_dump({"priors": {race: asdict(prior)}}))
    detail_path = out / f"data/live/races/{race}.json"
    detail = json.loads(detail_path.read_text())
    summary = json.loads((out / "data/live/summary.json").read_text())["states"][0]
    for payload in (detail, summary):
        assert payload["status"] == status
        if status == "waiting":
            assert payload == {"state": state, "race": race, "race_type": "senate", "district": None,
                               "as_of": snap.as_of, "status": "waiting", "modeled": True}
    report = public_json.check_tree(out, priors=private, mode="live")
    assert report.files == 2 and report.private_values_checked
    assert public_json.main([str(out), "--mode", "live", "--priors", str(private)]) == 0
    output = capsys.readouterr().out
    assert "PASS" in output
    for value in asdict(prior).values():
        assert str(value) not in output
    # Mutations prove that this integration check detects a copied private input,
    # written into text or (where the model publishes a margin) into a number.
    mutations = [lambda d: d.update(as_of=f"private value = {prior.margin}")]
    if "margin" in detail:
        mutations.append(lambda d: d["margin"].update(median=round(prior.margin, 4)))
    original = json.dumps(detail)
    for mutate in mutations:
        copied = json.loads(original)
        mutate(copied)
        detail_path.write_text(json.dumps(copied))
        assert public_json.main([str(out), "--mode", "live", "--priors", str(private)]) == 1
        output = capsys.readouterr().out
        assert str(prior.margin) not in output


def test_waiting_public_payload_is_identical_under_changed_private_priors(tmp_path):
    payloads = []
    for n, prior in enumerate(CANARIES):
        m = model(prior)
        snap = snapshot("GA", "empty")
        update = publish.StateUpdate("GA", "2026-GA-SEN", {"D": "Dem", "R": "Rep"},
                                     m.run(snap, n_draws=100, seed=7), m, None,
                                     race_type="senate", district=None, ranked_choice=False)
        out = tmp_path / str(n)
        publish.publish([update], publish.LocalWriter(out), mode="live")
        payloads.append(json.loads((out / "data/live/races/2026-GA-SEN.json").read_text()))
    assert payloads[0] == payloads[1] == {
        "state": "GA", "race": "2026-GA-SEN", "race_type": "senate", "district": None,
        "as_of": None, "status": "waiting", "modeled": True,
    }
