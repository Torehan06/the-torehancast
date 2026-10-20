"""Live poller: official feed → adapter → model → publisher, once per cycle.

    python -m torehancast.poller --out out/live --once          # one cycle, local files
    python -m torehancast.poller --gcs-bucket torehancast-2026-data  # election night

Only races whose feed is `ready` in config/feeds.yaml are polled. Config is re-read
every cycle, so a feed URL or contest name can be swapped on the night without a
restart. One race failing never stops the others: its last good update keeps being
published, and its own `as_of` shows how old it is.

Two guards protect the published numbers:
- Before a state's polls close, its counts are test data (Minnesota's files already
  carried some in October) and the race is published as waiting.
- Once votes exist, the configured D and R ballot names must both appear in the
  feed. If one is missing, the candidate map is wrong, and publishing would hand
  that side's votes to "other"; the race keeps its last good update instead.
"""

from __future__ import annotations

import argparse
import logging
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import config as configuration
from . import publish
from .adapters.fl_dos import BatchTracker
from .candidates import CandidateMap
from .config import Config, FeedConfig, RaceConfig
from .http import PoliteClient
from .model.simulate import RaceModel, RacePrior
from .replay import harness
from .schema import Snapshot

log = logging.getLogger("torehancast.poller")

DEFAULT_INTERVAL = 20.0  # seconds; the data bucket's cache max-age is 20s too
SEED = 0  # fixed, so an unchanged feed republishes identical numbers


def fetch_snapshot(client: PoliteClient, feed: FeedConfig, race_id: str, cmap: CandidateMap) -> Snapshot:
    """One fetch of one race, parsed by that state's adapter."""
    contest, eid = feed.contest, feed.election_id
    if feed.adapter == "ga_enhanced_voting":
        from .adapters import ga_enhanced_voting as ga

        return ga.snapshot_from_docs(ga.fetch_all(client, eid), contest, cmap, race_id)
    if feed.adapter == "nc_sbe":
        from .adapters import nc_sbe

        return nc_sbe.parse(nc_sbe.read_zip(client.get(feed.url)), contest, cmap, race_id)
    if feed.adapter == "fl_dos":
        from .adapters import fl_dos

        return fl_dos.parse(client.post(feed.url, dict(feed.params)).decode("latin-1"), contest, cmap, race_id)
    if feed.adapter == "ia_clarity":
        from .adapters import ia_clarity

        return ia_clarity.parse(ia_clarity.fetch(client, eid), contest, cmap, race_id)
    if feed.adapter == "sc_clarity":
        from .adapters import sc_clarity

        return sc_clarity.parse(sc_clarity.fetch(client, eid), contest, cmap, race_id)
    if feed.adapter == "mn_sos":
        from .adapters import mn_sos

        return mn_sos.parse(client.get(feed.url).decode("utf-8-sig"), contest, cmap, race_id)
    if feed.adapter == "ak_doe":
        from .adapters import ak_doe

        return ak_doe.parse(ak_doe.fetch(client, feed.url), contest, cmap, race_id)
    raise NotImplementedError(f"no live fetch for adapter {feed.adapter!r}")


Fetch = Callable[[PoliteClient, FeedConfig, str, CandidateMap], Snapshot]


@dataclass
class _Race:
    key: tuple  # what the model was built from; a config change rebuilds it
    model: RaceModel
    tracker: BatchTracker | None  # Florida only: one per race for the whole night
    last: publish.StateUpdate | None = None


@dataclass
class Poller:
    writer: object
    config_dir: Path = configuration.DEFAULT_CONFIG_DIR
    client: PoliteClient | None = None
    fetch: Fetch = fetch_snapshot
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    n_draws: int = 4000
    gate: str = "first_votes"
    _config: Config | None = None
    _races: dict[str, _Race] = field(default_factory=dict)

    def cycle(self) -> None:
        try:
            self._config = configuration.load_config(self.config_dir)
        except configuration.ConfigError as exc:
            if self._config is None:
                raise
            log.error("config invalid, keeping the previous one: %s", exc)
        cfg = self._config
        for race_id, race in cfg.races.items():
            feed = cfg.feeds[race_id]
            if feed.status != "ready":
                continue
            try:
                self._poll(race_id, race, feed, cfg.priors[race_id])
            except Exception as exc:  # one broken feed must not stop the others
                log.error("%s: %s: %s", race_id, type(exc).__name__, exc)
        updates = [r.last for rid, r in self._races.items()
                   if r.last is not None and cfg.feeds.get(rid) and cfg.feeds[rid].status == "ready"]
        if not updates:
            # A summary with no races is invalid public JSON; leave the last one in place.
            log.warning("no ready feed has produced an update; nothing published")
            return
        publish.publish(updates, self.writer, mode="live", gate=self.gate)

    def _race(self, race_id: str, race: RaceConfig, prior: RacePrior, adapter: str) -> _Race:
        key = (race.baseline, race.tau_pair, prior)
        current = self._races.get(race_id)
        if current is None or current.key != key:
            model = harness.make_model(race.state, race.baseline, race.tau_pair, prior,
                                       harness.live_synthetic_split(race.state))
            tracker = BatchTracker() if adapter == "fl_dos" else None
            last = current.last if current else None
            current = self._races[race_id] = _Race(key, model, tracker, last)
        return current

    def _poll(self, race_id: str, race: RaceConfig, feed: FeedConfig, prior: RacePrior | None) -> None:
        if prior is None:
            raise ValueError("ready feed but no private prior; not modeling this race")
        state = self._race(race_id, race, prior, feed.adapter)
        cmap = CandidateMap(feed.candidates)
        snap = self.fetch(self.client, feed, race_id, cmap)
        now = self.clock()
        votes = sum(snap.totals().values())
        if now < feed.polls_close_at:
            if votes:
                log.warning("%s: %d votes before polls close: treated as test data", race_id, votes)
            snap = Snapshot(snap.state, snap.race, snap.as_of, [])
        else:
            totals = snap.totals()
            if votes and not {"D", "R"} <= totals.keys():
                raise ValueError(f"feed has votes but no {sorted({'D', 'R'} - totals.keys())} ballot name; "
                                 "check candidates in feeds.yaml")
            if state.tracker is not None:
                snap = state.tracker.split(snap)
        for warning in snap.warnings:
            log.warning("%s: %s", race_id, warning)
        result = state.model.run(snap, self.n_draws, SEED)
        as_of = snap.as_of or now.isoformat(timespec="seconds")
        state.last = publish.StateUpdate(race.state, race_id, dict(feed.display), result, state.model, as_of,
                                         votes=snap.totals())

    def run_forever(self, interval: float = DEFAULT_INTERVAL) -> None:
        stopping = False

        def stop(*_):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        while not stopping:
            started = time.monotonic()
            try:
                self.cycle()
            except Exception:
                log.exception("cycle failed")
            time.sleep(max(0.0, interval - (time.monotonic() - started)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--out", type=Path, help="write data/live/ under this local directory")
    target.add_argument("--gcs-bucket", help="write data/live/ to this public GCS data bucket")
    parser.add_argument("--config-dir", type=Path, default=configuration.DEFAULT_CONFIG_DIR)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    parser.add_argument("--draws", type=int, default=4000)
    parser.add_argument("--gate", choices=publish.GATES, default="first_votes")
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    writer = publish.LocalWriter(args.out) if args.out else publish.GCSWriter(args.gcs_bucket)
    poller = Poller(writer, args.config_dir, PoliteClient(), n_draws=args.draws, gate=args.gate)
    if args.once:
        poller.cycle()
    else:
        poller.run_forever(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
