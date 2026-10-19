"""Aggregate candidate-specific election draws without guessing ranked transfers.

This is an output layer, not a transfer model. Each column is one candidate and
rows are paired simulated elections. First choices include *every* candidate;
pooled ``other`` votes cannot establish an individual's majority. Final-round
inputs must come from an RCV-aware model informed by the ranked count, never
from the existing two-party model. Absent that evidence, overall wins stay null.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RCVResult:
    p_outright: dict[str, float]
    p_via_rcv: dict[str, float | None]
    p_win: dict[str, float | None]
    p_no_rcv_needed: float
    status: str


def _matrix(draws: Mapping[str, Sequence[float]]) -> tuple[list[str], np.ndarray]:
    if not draws or any(not isinstance(key, str) or not key or key == "other" for key in draws):
        raise ValueError("RCV draws require individual candidate keys; pooled 'other' is unsupported")
    keys = list(draws)
    arrays = [np.asarray(draws[key], dtype=float) for key in keys]
    if any(a.ndim != 1 or not a.size for a in arrays) or len({a.size for a in arrays}) != 1:
        raise ValueError("candidate draws must be nonempty, one-dimensional, and paired")
    matrix = np.column_stack(arrays)
    if not np.isfinite(matrix).all() or (matrix < 0).any():
        raise ValueError("candidate votes must be finite and nonnegative")
    return keys, matrix


def summarize(
    first_choice: Mapping[str, Sequence[float]],
    *,
    final_round: Mapping[str, Sequence[float]] | None = None,
) -> RCVResult:
    """Compute disjoint outright / RCV wins over equally weighted paired draws.

    An outright winner has strictly more than half of all first-choice votes.
    ``final_round`` contains terminal continuing-candidate totals in the *same*
    draws, after transfers and exhaustion; omitted candidates have been eliminated.
    At most two candidates may have positive terminal votes in any draw.

    Missing transfers, a tied terminal round, or no continuing votes leave all
    overall/transfer probabilities unknown. We never discard unresolved draws and
    renormalize the remainder. First-round majorities need no transfer evidence.
    """
    keys, first = _matrix(first_choice)
    totals = first.sum(axis=1)
    if len(keys) < 2 or not np.isfinite(totals).all() or (totals <= 0).any():
        raise ValueError("first-choice draws need at least two candidates and positive finite totals")
    outright = first > totals[:, None] / 2
    needs_rcv = ~outright.any(axis=1)
    p_outright = dict(zip(keys, outright.mean(axis=0).tolist()))
    p_no_rcv_needed = float((~needs_rcv).mean())
    via = np.zeros_like(outright)
    status = "resolved"

    if final_round is not None:
        final_keys, final = _matrix(final_round)
        if not set(final_keys) <= set(keys) or final.shape[0] != first.shape[0]:
            raise ValueError("terminal draws must use first-choice candidates and paired rows")
        final_totals = final.sum(axis=1)
        if not np.isfinite(final_totals).all() or (final_totals > totals + 1e-8).any():
            raise ValueError("terminal rounds cannot create votes")
        if ((final > 0).sum(axis=1) > 2).any():
            raise ValueError("terminal rounds must contain at most two continuing candidates")
        winners = final > final_totals[:, None] / 2
        for j, key in enumerate(final_keys):
            via[:, keys.index(key)] = needs_rcv & winners[:, j]
        if (needs_rcv & ~via.any(axis=1)).any():
            status = "unresolved"
    elif needs_rcv.any():
        status = "awaiting_rcv"

    if status != "resolved":
        return RCVResult(p_outright, dict.fromkeys(keys), dict.fromkeys(keys), p_no_rcv_needed, status)
    p_via = dict(zip(keys, via.mean(axis=0).tolist()))
    p_win = {key: p_outright[key] + p_via[key] for key in keys}
    return RCVResult(p_outright, p_via, p_win, p_no_rcv_needed, status)
