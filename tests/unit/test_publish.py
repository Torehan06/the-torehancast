"""The published JSON must never reveal the hand-entered priors for a live state
that has no votes yet."""

import json

import pytest

from torehancast import publish
from torehancast.replay import harness
from torehancast.schema import Snapshot

WAITING_KEYS = {"state", "race", "as_of", "status"}


@pytest.fixture(scope="module")
def ga():
    model, _ = harness.build_model("GA", "primary")
    return model


def _update(model, snap):
    result = model.run(snap, 2000, 0)
    return publish.StateUpdate("GA", "US Senate", {"D": "Dem", "R": "Rep"}, result, model, snap.as_of)


def _first_county_batch():
    final = harness.final_result("GA", "2022_sen")
    cells = [c for c in final.cells if c.unit_id == "APPLING" and c.vote_type == "early"]
    return Snapshot("GA", "x", "T+0.25h", cells, cell_complete={("APPLING", "early"): 1.0})


def test_live_state_without_votes_publishes_only_waiting(ga, tmp_path):
    update = _update(ga, Snapshot("GA", "x", None, []))
    publish.publish([update], publish.LocalWriter(tmp_path), mode="live")
    detail = json.loads((tmp_path / "data/live/GA.json").read_text())
    summary = json.loads((tmp_path / "data/live/summary.json").read_text())
    assert set(detail) == WAITING_KEYS and detail["status"] == "waiting"
    assert set(summary["states"][0]) == WAITING_KEYS
    # Belt and braces: no number anywhere in the state's payloads.
    text = json.dumps(detail) + json.dumps(summary["states"])
    assert not any(ch.isdigit() for ch in text.replace("GA", "").replace("T+", ""))  # as_of is None here


def test_live_state_with_votes_is_published(ga, tmp_path):
    update = _update(ga, _first_county_batch())
    payload = publish.state_detail(update, "live")
    assert payload["status"] == "live" and "p_win" in payload and payload["counties"]


def test_data_weight_gate_holds_back_thin_data(ga):
    update = _update(ga, _first_county_batch())
    assert ga.last_data_weight < publish.DATA_WEIGHT_RELEASE  # one small county says little
    assert publish.state_summary(update, "live", gate="data_weight")["status"] == "waiting"
    assert publish.state_summary(update, "live", gate="first_votes")["status"] == "live"


def test_replay_is_always_published(ga):
    update = _update(ga, Snapshot("GA", "x", None, []))
    assert publish.state_summary(update, "replay")["status"] == "live"


def test_s3_writer_refuses_keys_outside_data():
    class Fake:
        def put_object(self, **kw):
            raise AssertionError("should not be called")

    w = publish.S3Writer("bucket", client=Fake())
    with pytest.raises(ValueError):
        w.write("config/priors.yaml", {})
