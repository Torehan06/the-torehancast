"""Results-only races publish observed counts, never model forecasts."""

import json
from dataclasses import replace

import pandas as pd
import pytest

from torehancast import public_json, publish
from torehancast.model.composition import CompositionPrior
from torehancast.model.simulate import RaceModel, RacePrior
from torehancast.model.tau import HistoricalParams
from torehancast.schema import ALL, Cell, Snapshot


@pytest.fixture
def modeled():
    baseline = pd.DataFrame([{"unit_id": "A", "vote_type": ALL, "D": 490, "R": 450}])
    params = HistoricalParams(0.04, 0.08, 0.03, 0.05, CompositionPrior(0.2, 0.1, 0.1, 0.05), 1000)
    model = RaceModel(baseline, RacePrior(0, 0.1, 1, 0.1), params)
    snapshot = Snapshot("GA", "Senate", "now", [Cell("A", ALL, {"D": 490, "R": 450})])
    return publish.StateUpdate("GA", "2026-GA-SEN", {"D": "Dem", "R": "Rep"},
                               model.run(snapshot, n_draws=100, seed=0), model, "now",
                               race_type="senate", district=None, ranked_choice=False)


def results_only(**changes):
    fields = dict(state="VA", race="2026-VA-SEN", candidates={"D": "Dem", "R": "Rep", "I": "Ind"},
                  votes={"D": 50, "R": 30, "I": 20}, pct_reporting=0.25, as_of="now",
                  race_type="senate", district=None)
    return publish.ResultsOnlyUpdate(**(fields | changes))


def in_state(update, state):
    """The same update moved to another state's Senate race (ME and AK are ranked-choice)."""
    if isinstance(update, publish.StateUpdate):
        update = replace(update, ranked_choice=state in ("ME", "AK"))
    return replace(update, state=state, race=f"2026-{state}-SEN")


def waiting(state, modeled):
    return {"state": state, "race": f"2026-{state}-SEN", "race_type": "senate", "district": None,
            "as_of": "now", "status": "waiting", "modeled": modeled}


@pytest.mark.parametrize("state", ["GA", "ME", "AK"])
@pytest.mark.parametrize("mode", ["live", "replay"])
def test_every_modeled_output_explicitly_identifies_forecasts(modeled, state, mode):
    update = in_state(modeled, state)
    for render in (publish.state_summary, publish.state_detail):
        assert render(update, mode)["modeled"] is True
    held = replace(update, result=replace(update.result, reported_votes=0))
    assert publish.state_summary(held, "live") == waiting(state, True)


@pytest.mark.parametrize("mode", ["live", "replay"])
@pytest.mark.parametrize("state", ["VA", "ME", "AK"])
def test_results_only_summary_has_only_observed_data_and_no_detail_file(tmp_path, mode, state):
    publish.publish([in_state(results_only(), state)], publish.LocalWriter(tmp_path), mode, gate="data_weight")
    detail = publish.state_detail(in_state(results_only(), state), mode)
    summary = json.loads((tmp_path / f"data/{mode}/summary.json").read_text())["states"][0]
    assert not (tmp_path / f"data/{mode}/races").exists()  # detail files are for modeled races
    expected = {
        "state": state, "race": f"2026-{state}-SEN", "race_type": "senate", "district": None,
        "as_of": "now", "status": "live", "modeled": False,
        "candidates": {"D": "Dem", "R": "Rep", "I": "Ind"},
        "votes": {"D": 50, "R": 30, "I": 20},
        "vote_share": {"D": 0.5, "R": 0.3, "I": 0.2}, "pct_reporting": 0.25,
    }
    assert detail == summary == expected


@pytest.mark.parametrize("mode", ["live", "replay"])
def test_results_only_zero_votes_wait_even_if_feed_reports_completion(mode):
    update = results_only(votes={"D": 0, "R": 0, "I": 0}, pct_reporting=1.0)
    for render in (publish.state_summary, publish.state_detail):
        assert render(update, mode) == waiting("VA", False)


def test_unknown_reporting_is_not_inferred_from_candidate_totals():
    assert publish.state_summary(results_only(pct_reporting=None), "live")["pct_reporting"] is None


@pytest.mark.parametrize("changes", [
    {"votes": {"D": -1, "R": 30, "I": 20}},
    {"votes": {"D": True, "R": 30, "I": 20}},
    {"votes": {"D": 1.5, "R": 30, "I": 20}},
    {"votes": {"D": 50, "R": 30}},
    {"votes": {"D": 50, "R": 30, "I": 20, "unknown": 1}},
    {"candidates": {}, "votes": {}},
    {"pct_reporting": -0.1}, {"pct_reporting": 1.1},
    {"pct_reporting": float("nan")}, {"pct_reporting": True},
])
def test_invalid_observed_results_are_rejected_before_writing(tmp_path, changes):
    with pytest.raises(ValueError):
        publish.publish([results_only(**changes)], publish.LocalWriter(tmp_path), "live")
    assert not list(tmp_path.rglob("*.json"))


def test_mixed_races_pass_the_public_checker(modeled, tmp_path):
    publish.publish([modeled, results_only()], publish.LocalWriter(tmp_path), "replay")
    assert public_json.check_tree(tmp_path).files == 2  # summary.json + races/2026-GA-SEN.json


@pytest.mark.parametrize("field", ["p_win", "p_outright", "p_via_rcv", "p_no_rcv_needed",
                                   "margin", "expected_votes", "share_counted", "counties", "rcv_status"])
def test_checker_rejects_any_forecast_on_results_only_payload(tmp_path, field):
    payload = publish.state_summary(results_only(), "replay")
    document = {"generated_at": "2026-11-03T20:00:00+00:00", "mode": "replay", "states": [payload]}
    (tmp_path / "summary.json").write_text(json.dumps(document))
    assert public_json.check_tree(tmp_path).files == 1
    payload[field] = None
    (tmp_path / "summary.json").write_text(json.dumps(document))
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path)


@pytest.mark.parametrize("flag", [None, 0, 1, "false"])
def test_checker_requires_a_boolean_modeled_flag(modeled, tmp_path, flag):
    payload = publish.state_summary(modeled, "replay")
    payload["modeled"] = flag
    (tmp_path / "races").mkdir()
    (tmp_path / "races/2026-GA-SEN.json").write_text(json.dumps(payload))
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path)


def test_modeled_race_publishes_observed_votes_with_other_in_the_denominator(modeled):
    update = replace(modeled, votes={"D": 490, "R": 450, "other": 60})
    for render in (publish.state_summary, publish.state_detail):
        out = render(update, "live")
        assert out["votes"] == {"D": 490, "R": 450}  # display candidates only
        assert out["vote_share"] == {"D": 0.49, "R": 0.45}  # ÷ 1,000, not ÷ 940
        assert "pct_reporting" not in out  # the model's share_counted covers progress
        assert "p_win" in out  # forecasts are unchanged alongside the counts


def test_rcv_races_carry_votes_too(modeled):
    out = publish.state_summary(replace(in_state(modeled, "AK"), votes={"D": 10, "R": 30, "other": 0}), "live")
    assert out["rcv_status"] == "awaiting_first_choices"
    assert out["votes"] == {"D": 10, "R": 30} and out["vote_share"] == {"D": 0.25, "R": 0.75}


def test_waiting_payload_never_gains_votes(modeled):
    waiting = replace(modeled, votes={"D": 0, "R": 0}, result=replace(modeled.result, reported_votes=0))
    assert set(publish.state_summary(waiting, "live")) == {"state", "race", "race_type", "district",
                                                           "as_of", "status", "modeled"}


def test_empty_count_publishes_zeros_but_a_missing_candidate_with_votes_raises(modeled):
    assert publish.state_summary(replace(modeled, votes={}), "replay")["vote_share"] == {"D": 0.0, "R": 0.0}
    with pytest.raises(ValueError, match="lack display candidates"):
        publish.state_summary(replace(modeled, votes={"D": 5, "other": 1}), "live")
    with pytest.raises(ValueError, match="nonnegative"):
        publish.state_summary(replace(modeled, votes={"D": -1, "R": 2}), "live")


def test_votes_stay_unpublished_when_the_caller_supplies_none(modeled):
    assert "votes" not in publish.state_summary(modeled, "live")


def test_a_contest_not_in_the_feed_yet_waits():
    absent = results_only(candidates={}, votes={}, pct_reporting=None, in_feed=False)
    assert publish.state_summary(absent, "live") == waiting("VA", False)
    with pytest.raises(ValueError):
        publish.state_summary(replace(absent, votes={"D": 1}, candidates={"D": "Dem"}), "live")
