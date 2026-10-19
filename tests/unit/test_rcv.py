"""Hand-counted candidate draws: plurality is not an RCV win probability."""

import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from torehancast import publish
from torehancast.model import rcv
from torehancast.model.composition import CompositionPrior
from torehancast.model.simulate import RaceModel, RacePrior
from torehancast.model.tau import HistoricalParams
from torehancast.schema import ALL, Cell, Snapshot

FIRST = {"D": [60, 30, 40, 45], "R": [30, 60, 35, 35], "ind": [10, 10, 25, 20]}
# Rows correspond to the same simulated elections as FIRST. Some ballots exhaust.
FINAL = {"D": [60, 30, 55, 45], "R": [30, 60, 40, 50]}


def test_first_choice_plurality_does_not_become_an_overall_win():
    result = rcv.summarize(FIRST)
    assert result.p_outright == {"D": 0.25, "R": 0.25, "ind": 0.0}
    assert result.p_no_rcv_needed == 0.5
    assert result.p_win == {"D": None, "R": None, "ind": None}
    assert result.p_via_rcv == {"D": None, "R": None, "ind": None}
    assert result.status == "awaiting_rcv"


def test_terminal_rounds_resolve_disjoint_win_paths_with_exhausted_ballots():
    result = rcv.summarize(FIRST, final_round=FINAL)
    assert result.p_outright == {"D": 0.25, "R": 0.25, "ind": 0.0}
    assert result.p_via_rcv == {"D": 0.25, "R": 0.25, "ind": 0.0}
    assert result.p_win == {"D": 0.5, "R": 0.5, "ind": 0.0}
    assert result.p_no_rcv_needed == 0.5
    assert result.status == "resolved"
    for candidate in FIRST:
        assert result.p_win[candidate] == result.p_outright[candidate] + result.p_via_rcv[candidate]


def test_independent_candidate_can_win_outright():
    result = rcv.summarize({"D": [20], "R": [25], "ind": [55]})
    assert result.p_win == {"D": 0.0, "R": 0.0, "ind": 1.0}
    assert result.p_via_rcv == {"D": 0.0, "R": 0.0, "ind": 0.0}
    assert result.p_no_rcv_needed == 1.0


def test_independent_candidate_can_win_through_rcv():
    result = rcv.summarize(
        {"D": [30], "R": [40], "ind": [30]},
        final_round={"R": [45], "ind": [50]},
    )
    assert result.p_outright == {"D": 0.0, "R": 0.0, "ind": 0.0}
    assert result.p_via_rcv == {"D": 0.0, "R": 0.0, "ind": 1.0}
    assert result.p_win["ind"] == 1.0


def test_exactly_half_is_not_an_outright_win():
    result = rcv.summarize({"D": [50], "R": [40], "ind": [10]})
    assert result.p_outright == {"D": 0.0, "R": 0.0, "ind": 0.0}
    assert result.p_no_rcv_needed == 0.0
    assert result.p_win["D"] is None


def test_tied_terminal_round_is_unresolved_instead_of_assigned_to_r():
    result = rcv.summarize(
        {"D": [40, 60], "R": [40, 30], "ind": [20, 10]},
        final_round={"D": [50, 60], "R": [50, 30]},
    )
    assert result.status == "unresolved"
    assert result.p_win == {"D": None, "R": None, "ind": None}
    assert result.p_no_rcv_needed == 0.5


def test_fully_exhausted_terminal_round_does_not_invent_a_winner():
    result = rcv.summarize({"D": [40], "R": [40], "ind": [20]},
                           final_round={"D": [0], "R": [0]})
    assert result.p_win["D"] is None


@pytest.mark.parametrize("first", [
    {}, {"D": [100]}, {"D": [], "R": []},
    {"D": [30, 40], "R": [20]}, {"D": [[30]], "R": [[20]]},
    {"D": [-1], "R": [20]}, {"D": [np.nan], "R": [20]},
    {"D": [np.inf], "R": [20]}, {"D": [0], "R": [0]},
    {"D": [40], "R": [30], "other": [30]},
])
def test_invalid_or_pooled_first_choice_inputs_are_rejected(first):
    with pytest.raises(ValueError):
        rcv.summarize(first)


@pytest.mark.parametrize("final", [
    {"D": [55], "R": [40]},  # unpaired draws
    {"D": [55] * 4, "unknown": [40] * 4},
    {"D": [55] * 4, "R": [50] * 4},  # creates votes
    {"D": [40] * 4, "R": [35] * 4, "ind": [25] * 4},  # not terminal
    {"D": [np.nan] * 4, "R": [40] * 4},
    {"D": [-1] * 4, "R": [40] * 4},
    {},
])
def test_invalid_terminal_inputs_fail_loudly(final):
    with pytest.raises(ValueError):
        rcv.summarize(FIRST, final_round=final)


@pytest.fixture
def update():
    baseline = pd.DataFrame([{"unit_id": "A", "vote_type": ALL, "D": 490, "R": 450}])
    params = HistoricalParams(0.04, 0.08, 0.03, 0.05, CompositionPrior(0.2, 0.1, 0.1, 0.05), 1000)
    model = RaceModel(baseline, RacePrior(0, 0.1, 1, 0.1), params)
    snap = Snapshot("ME", "Senate", "T+1h", [Cell("A", ALL, {"D": 490, "R": 450, "ind": 60})],
                    cell_complete={("A", ALL): 1.0})
    result = model.run(snap, n_draws=100, seed=1)
    assert result.p_win["D"] == 1.0  # precisely the false confidence RCV must suppress
    return publish.StateUpdate("ME", "Senate", {"D": "Dem", "R": "Rep", "ind": "Independent"},
                               result, model, snap.as_of)


@pytest.mark.parametrize("state", ["ME", "AK"])
def test_rcv_states_fail_closed_without_candidate_draws(update, state, tmp_path):
    update = replace(update, state=state)
    publish.publish([update], publish.LocalWriter(tmp_path), mode="live")
    detail = json.loads((tmp_path / f"data/live/{state}.json").read_text())
    summary = json.loads((tmp_path / "data/live/summary.json").read_text())["states"][0]
    for payload in (detail, summary):
        assert payload["p_win"] == {"D": None, "R": None, "ind": None}
        assert payload["rcv_status"] == "awaiting_first_choices"
        assert payload["p_no_rcv_needed"] is None
        assert not {"margin", "counties", "expected_votes", "share_counted"} & payload.keys()


def test_rcv_components_reach_both_public_files(update, tmp_path):
    update = replace(update, rcv=rcv.summarize(FIRST, final_round=FINAL))
    publish.publish([update], publish.LocalWriter(tmp_path), mode="live")
    detail = json.loads((tmp_path / "data/live/ME.json").read_text())
    summary = json.loads((tmp_path / "data/live/summary.json").read_text())["states"][0]
    for payload in (detail, summary):
        assert payload["p_win"] == {"D": 0.5, "R": 0.5, "ind": 0.0}
        assert payload["p_outright"] == {"D": 0.25, "R": 0.25, "ind": 0.0}
        assert payload["p_via_rcv"] == {"D": 0.25, "R": 0.25, "ind": 0.0}
        assert payload["p_no_rcv_needed"] == 0.5
        assert payload["rcv_status"] == "resolved"


def test_rcv_draws_cannot_bypass_live_waiting_gate(update):
    update = replace(update, result=replace(update.result, reported_votes=0), rcv=rcv.summarize(FIRST))
    for payload in (publish.state_summary(update, "live"), publish.state_detail(update, "live")):
        assert payload == {"state": "ME", "race": "Senate", "as_of": "T+1h", "status": "waiting", "modeled": True}


def test_replay_without_rcv_evidence_also_suppresses_two_party_probability(update):
    assert publish.state_summary(update, "replay")["p_win"]["D"] is None


def test_publisher_rejects_mismatched_candidate_keys(update):
    update = replace(update, rcv=rcv.summarize({"wrong": [60], "R": [40]}))
    with pytest.raises(ValueError):
        publish.state_summary(update, "live")


def test_plurality_race_output_still_uses_existing_model(update):
    payload = publish.state_detail(replace(update, state="GA"), "live")
    assert payload["p_win"]["D"] == 1.0
    assert "margin" in payload and "counties" in payload


@pytest.mark.parametrize("final", [
    {"D": [1], "R": [40]},  # continuing D cannot lose its first-choice ballots
    {"D": [45], "R": [1]},  # the same invariant for the other candidate
])
def test_terminal_round_cannot_remove_votes_from_a_continuing_candidate(final):
    with pytest.raises(ValueError, match="continuing"):
        rcv.summarize({"D": [45], "R": [40], "ind": [15]}, final_round=final)
