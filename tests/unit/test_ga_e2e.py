"""The native feed boundary must preserve votes and reporting evidence."""

import copy
import json
from pathlib import Path

import pytest

from torehancast import elections
from torehancast.adapters import ga_enhanced_voting as ga
from torehancast.replay import e2e
from torehancast.schema import Cell, Snapshot

FIX = Path(__file__).parents[1] / "fixtures" / "ga"


@pytest.fixture
def template():
    return json.loads((FIX / "2022NovGen_appling-county-ga.json").read_text())


def test_native_roundtrip_preserves_partial_votes_and_completion(template):
    election = elections.load("GA", "2022_sen")
    original = copy.deepcopy(template)
    snap = Snapshot("GA", election.key, "T+0.25h", [
        Cell("APPLING", "early", {"D": 120, "R": 200, "other": 3}),
        Cell("APPLING", "election_day", {"D": 11, "R": 22, "other": 1}),
    ], {"APPLING": 0.125}, {("APPLING", "early"): 1.0})
    docs = json.loads(json.dumps(e2e.render_ga(snap, [template], election)))
    parsed = ga.snapshot_from_docs(docs, election.spec["contest"], election.candidates, election.key)
    assert parsed.totals() == {"D": 131, "R": 222, "other": 4}
    assert parsed.unit_reporting == {"APPLING": 0.125}
    assert parsed.cell_complete[("APPLING", "early")] == 1.0
    assert ("APPLING", "election_day") not in parsed.cell_complete
    assert parsed.as_of == "T+0.25h"
    assert template == original
    item = ga.find_contest(docs[0], "US Senate")
    assert item["voteTotal"] == 357
    assert all(o["voteCount"] == sum(g["voteCount"] for g in o["groupResults"])
               for o in item["summaryResults"]["ballotOptions"])


def test_native_empty_poll_has_no_completed_cells(template):
    election = elections.load("GA", "2022_sen")
    docs = e2e.render_ga(Snapshot("GA", election.key, "T+0.00h", []), [template], election)
    parsed = ga.snapshot_from_docs(docs, "US Senate", election.candidates, election.key)
    assert sum(parsed.totals().values()) == 0
    assert not any(parsed.cell_complete.values())
    assert parsed.unit_reporting == {}


def test_multiple_other_candidates_recover_original_final_totals():
    template = json.loads((FIX / "2024NovGen_fulton-county-ga.json").read_text())
    election = elections.load("GA", "2024_pres")
    source = ga.snapshot_from_docs([template], election.spec["contest"], election.candidates, election.key)
    source.cell_complete = {(c.unit_id, c.vote_type): 1.0 for c in source.cells}
    rendered = e2e.render_ga(source, [template], election)
    options = ga.find_contest(rendered[0], election.spec["contest"])["summaryResults"]["ballotOptions"]
    assert {o["name"][0]["text"]: o["voteCount"] for o in options} == {
        "Donald J. Trump (Rep)": 144655, "Kamala D. Harris (Dem)": 384752,
        "Chase Oliver (Lib)": 2507, "Jill Stein (Grn)": 3324,
    }
    parsed = ga.snapshot_from_docs(rendered, election.spec["contest"], election.candidates, election.key)
    assert all(v == 1.0 for v in parsed.cell_complete.values())


@pytest.mark.parametrize("cell", [
    Cell("UNKNOWN", "early", {"D": 3}),
    Cell("APPLING", "unrecognised", {"D": 3}),
    Cell("APPLING", "early", {"unknown_candidate": 3}),
])
def test_renderer_does_not_silently_drop_unrepresentable_cells(template, cell):
    with pytest.raises(ValueError):
        e2e.render_ga(Snapshot("GA", "x", None, [cell]), [template], elections.load("GA", "2022_sen"))


@pytest.mark.parametrize("pair", ["primary", "secondary"])
def test_ga_native_replay_publishes_changing_frames_and_final_truth(pair, tmp_path):
    index = e2e.run(tmp_path, pair=pair, n_draws=300)
    frames = index["frames"]
    assert len(frames) > 5
    root = tmp_path / "data/replay"
    first = json.loads((root / frames[0]["summary"]).read_text())["states"][0]
    last = json.loads((root / frames[-1]["summary"]).read_text())["states"][0]
    latest = json.loads((root / "summary.json").read_text())["states"][0]
    assert first["reported_votes"] == 0
    assert last["reported_votes"] > 3_000_000
    assert last["share_counted"] == 1.0
    assert last == latest
    assert first["margin"] != last["margin"]
    assert first["as_of"] != last["as_of"]
    # Independent oracle: the archive's own native option totals, not the model.
    target = elections.load("GA", "2022_sen" if pair == "primary" else "2024_pres")
    totals = {"D": 0, "R": 0}
    for doc in ga.load_archive(elections.ARCHIVES / "GA" / target.spec["code"]):
        for option in ga.find_contest(doc, target.spec["contest"])["summaryResults"]["ballotOptions"]:
            side = target.spec["candidates"].get(option["name"][0]["text"])
            if side in totals:
                totals[side] += option["voteCount"]
    assert last["reported_votes"] == totals["D"] + totals["R"]
    assert last["margin"]["median"] == pytest.approx((totals["D"] - totals["R"]) / sum(totals.values()), abs=0.00005)
    assert json.loads((root / "index.json").read_text()) == index
