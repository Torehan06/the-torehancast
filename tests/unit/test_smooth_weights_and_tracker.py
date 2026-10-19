import numpy as np
import pytest

from torehancast.adapters.fl_dos import BatchTracker
from torehancast.model import composition
from torehancast.model.swing import measurement_sd
from torehancast.schema import ALL, Cell, Snapshot

GRID = np.linspace(0.02, 1.0, 2000)


@pytest.mark.parametrize("split", [True, False])
def test_measurement_noise_ramp_is_smooth_and_decreasing(split):
    sd = measurement_sd(GRID, 0.05, split)
    assert np.all(np.diff(sd) <= 1e-12), "noise must not rise as more of a county is counted"
    # No jumps: each small step in counted share changes the noise by < 5% relative,
    # or by a negligible absolute amount near the "fully counted" floor.
    step = np.abs(np.diff(sd))
    relative = step / sd[:-1]
    assert np.all((relative < 0.05) | (step < 1e-3))
    assert sd[-1] <= 1e-4 + 1e-12  # a fully counted county is (almost) exact


def test_partial_cell_weight_ramps_smoothly_from_zero():
    noise, extra = 0.05, composition.PARTIAL_GAP_SD
    f = np.linspace(composition.MIN_MEASURED, 1.0, 2000)
    w = 1.0 / (1.0 + (extra / noise) ** 2 * (1.0 - f) / f)
    assert w[0] < 0.01 and w[-1] == pytest.approx(1.0)
    assert np.all(np.diff(w) >= 0)
    assert np.max(np.diff(w)) < 0.01


def _snap(totals, reporting):
    cells = [Cell(u, ALL, {"D": d, "R": r}) for u, (d, r) in totals.items()]
    return Snapshot("FL", "x", None, cells, dict(reporting))


def test_batch_tracker_books_the_first_election_day_chunk_as_election_day():
    t = BatchTracker()
    t.split(_snap({"DADE": (600, 400)}, {"DADE": 0.0}))  # pre-Election-Day batch
    s = t.split(_snap({"DADE": (700, 600)}, {"DADE": 0.25}))  # first precincts in
    cells = {c.vote_type: c.votes for c in s.cells}
    assert cells["early"] == {"D": 600, "R": 400}
    assert cells["election_day"] == {"D": 100, "R": 200}
    assert s.cell_complete[("DADE", "early")] == 1.0


def test_batch_tracker_warns_when_split_is_unknowable():
    s = BatchTracker().split(_snap({"LEON": (500, 500)}, {"LEON": 0.5}))
    assert any("split unknown" in w for w in s.warnings)
