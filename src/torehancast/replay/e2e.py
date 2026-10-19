"""Offline GA replay through native JSON, the real adapter, model and publisher.

    python -m torehancast.replay.e2e --state GA --out out/
"""

from __future__ import annotations

import argparse
import copy
import json
from fractions import Fraction
from pathlib import Path

from .. import elections, publish
from ..adapters import ga_enhanced_voting as ga
from ..schema import Snapshot, canonical_vote_type
from . import arrivals, harness


def render_ga(snap: Snapshot, templates: list[dict], election: elections.Election) -> list[dict]:
    """Render cumulative synthetic counts in saved official county document shapes.

    Unreported groups are zeroed and explicitly not reported. Partial groups must
    stay partial even when early/mail normally arrive as one batch. Pooled minor
    candidates are apportioned by their archived per-group votes; final counts
    recover each original option exactly. This apportionment is synthetic.
    """
    cells = {(c.unit_id, c.vote_type): c.votes for c in snap.cells}
    if len(cells) != len(snap.cells):
        raise ValueError("duplicate replay cells")
    represented = set()
    docs = []
    for template in templates:
        doc = copy.deepcopy(template)
        item = ga.find_contest(doc, election.spec["contest"])
        if item is None:
            raise ValueError("archive county is missing the configured contest")
        doc["ballotItems"] = [item]
        uid = ga.unit_id(ga._text(doc["jurisdiction"]["name"]))
        groups = {}
        names = {}
        for option in item["summaryResults"]["ballotOptions"]:
            side = election.spec["candidates"].get(ga._text(option["name"]), "other")
            for group in option.get("groupResults") or []:
                vt = canonical_vote_type(ga._text(group["groupName"]))
                groups.setdefault((vt, side), []).append((group, int(group["voteCount"] or 0)))
                names[vt] = group["groupName"]
                represented.add((uid, vt, side))
        for (vt, side), weighted in groups.items():
            total = cells.get((uid, vt), {}).get(side, 0)
            if type(total) is not int or total < 0:
                raise ValueError("replay counts must be nonnegative integers")
            weight = sum(n for _, n in weighted)
            if total and not weight:
                raise ValueError("cannot assign votes to a zero-weight archived option")
            # Integer apportionment; assigning the remainder by fractional quota
            # preserves totals without ever inventing a new candidate option.
            counts = [total * n // weight if weight else 0 for _, n in weighted]
            order = sorted(range(len(weighted)), key=lambda j: -(total * weighted[j][1] % weight) if weight else 0)
            for j in order[:total - sum(counts)]:
                counts[j] += 1
            for (group, _), count in zip(weighted, counts):
                group["voteCount"] = count
        for option in item["summaryResults"]["ballotOptions"]:
            option["voteCount"] = sum(g["voteCount"] for g in option.get("groupResults") or [])
        item["voteTotal"] = sum(o["voteCount"] for o in item["summaryResults"]["ballotOptions"])
        fraction = snap.unit_reporting.get(uid)
        ratio = Fraction(fraction).limit_denominator(1_000_000) if fraction is not None else None
        item["reportingStatus"] = {
            "reportingUnits": ratio.numerator if ratio is not None else 0,
            "totalUnits": ratio.denominator if ratio is not None else 0,
            "asOf": snap.as_of,
        }
        doc["election"]["asOf"] = snap.as_of
        statuses = []
        for vt, name in names.items():
            known = snap.cell_complete.get((uid, vt))
            if known == 1.0:
                status = "fully-reported"
            elif (uid, vt) not in cells or known == 0.0:
                status = "not-reported"
            else:
                status = "partially-reported"
            statuses.append({"groupName": name, "reportingStatusClientTextKey": f"reporting-status-{status}"})
        doc["election"]["groupReportingStatus"] = statuses
        docs.append(doc)
    if any((c.unit_id, c.vote_type, side) not in represented for c in snap.cells for side in c.votes):
        raise ValueError("replay cell has no corresponding native county/group/candidate")
    return docs


class _FrameWriter:
    def __init__(self, writer: publish.LocalWriter, index: int):
        self.writer = writer
        self.prefix = f"data/replay/frames/{index:06d}/"

    def write(self, key: str, payload: dict) -> None:
        self.writer.write(self.prefix + key.removeprefix("data/replay/"), payload)


def run(
    out: Path, *, state: str = "GA", pair: str = "primary", order: str = "random",
    seed: int = 0, n_draws: int = 4000,
) -> dict:
    """Publish each synthetic poll interval and index, retaining the final latest files.

    No live configuration, network access, or cloud writer is used. Output must be
    a fresh replay directory, so previous runs cannot leave stale frames behind.
    """
    out = Path(out)
    if state != "GA":
        raise ValueError("native end-to-end replay currently supports GA only")
    if order not in arrivals.ORDERS or n_draws <= 0:
        raise ValueError("invalid order or simulation draw count")
    replay_root = out / "data/replay"
    if replay_root.exists():
        raise ValueError("replay output already exists; choose a fresh --out directory")
    model, spec = harness.build_model(state, pair)
    election = elections.load(state, spec["target"])
    templates = ga.load_archive(elections.ARCHIVES / state / election.spec["code"])
    units = [ga.unit_id(ga._text(doc["jurisdiction"]["name"])) for doc in templates]
    if len(units) != len(set(units)) or set(units) != set(model.baseline.unit_id):
        raise ValueError("GA archive county coverage must be complete and unique")
    final = ga.snapshot_from_docs(templates, election.spec["contest"], election.candidates, election.key)
    if not final.cells:
        raise ValueError("target archive is empty")
    events = arrivals.timeline(final, order, seed, harness.arrival_profile(harness.replay_config(state)))
    writer = publish.LocalWriter(out)
    candidates = {side: name for name, side in election.spec["candidates"].items()}
    index = {"state": state, "pair": pair, "order": order, "seed": seed, "frames": []}
    for i, (time, snap) in enumerate(arrivals.snapshots(final, events)):
        # Force the actual serialization boundary; never pass synthetic cells to
        # the model or an adapter wrapper that bypasses native parsing.
        native = json.loads(json.dumps(render_ga(snap, templates, election)))
        parsed = ga.snapshot_from_docs(native, election.spec["contest"], election.candidates, election.key)
        result = model.run(parsed, n_draws, seed)
        update = publish.StateUpdate(state, election.key, candidates, result, model, parsed.as_of)
        publish.publish([update], _FrameWriter(writer, i), mode="replay")
        publish.publish([update], writer, mode="replay")
        index["frames"].append({"time": time, "summary": f"frames/{i:06d}/summary.json"})
    writer.write("data/replay/index.json", index)
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, choices=["GA"])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pair", default="primary", choices=["primary", "secondary"])
    parser.add_argument("--order", default="random", choices=arrivals.ORDERS)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--draws", type=int, default=4000)
    args = parser.parse_args(argv)
    try:
        index = run(args.out, state=args.state, pair=args.pair, order=args.order, seed=args.seed, n_draws=args.draws)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"Replay failed: {exc}\n")
    print(f"GA {args.pair}: published {len(index['frames'])} native-feed replay frames to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
