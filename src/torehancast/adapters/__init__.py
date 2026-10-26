"""Adapter registry: the `adapter:` name in config → the module that reads that feed.

Every adapter module exposes the same functions, so the poller and the replay code
never branch on a state, and a new adapter never edits a shared file:

    fetch_source(client, feed) -> document
        One cycle's download for a feed (several requests for Georgia). The poller
        fetches each distinct source once per cycle, however many races it serves.
    parse(document, contest, cmap, race) -> Snapshot
        One modeled race out of a document.
    final_snapshot(spec, archives, cmap, key) -> Snapshot
        The certified result, from the archived official files in `archives`
        (data/archives/<ST>). `spec` is the election's entry in elections.yaml.
    parse_all_contests(document, contests) -> {race_id: ContestTotals}   (optional)
        Vote totals for every results-only contest in one pass. A contest missing
        from the result has no votes yet. Adapters gain this in W4.
"""

from __future__ import annotations

import importlib
import re
from types import ModuleType

REQUIRED = ("fetch_source", "parse", "final_snapshot")


def get(name: str) -> ModuleType:
    """The adapter module called `name`; raises NotImplementedError for an unknown one."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name or ""):
        raise NotImplementedError(f"no adapter {name!r}")
    try:
        module = importlib.import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        if exc.name != f"{__name__}.{name}":
            raise  # the adapter exists but one of its own imports is broken
        raise NotImplementedError(f"no adapter {name!r}") from None
    if missing := [f for f in REQUIRED if not hasattr(module, f)]:
        raise NotImplementedError(f"adapter {name!r} lacks {', '.join(missing)}")
    return module
