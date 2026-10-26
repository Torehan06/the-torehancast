"""Live poller: official feed → adapter → model → publisher, once per cycle.

    python -m torehancast.poller --out out/live --once          # one cycle, local files
    python -m torehancast.poller --gcs-bucket torehancast-2026-data  # election night

Modeled races are polled when their feed is `ready` in config/feeds.yaml; results-only
races when their source is `ready` in config/results/<ST>.yaml. Config is re-read
every cycle, so a feed URL or contest name can be swapped on the night without a
restart. Each cycle:

1. Every distinct source is fetched once, however many races it serves (Georgia's
   House races reuse the Senate download), by a small thread pool with a deadline.
   Modeled sources are fetched every cycle, results-only ones every 60 s. A source
   still downloading at the deadline is picked up by a later cycle, and a failed
   fetch keeps the source's last good document.
2. Modeled races rerun the model only when their document (or config, or the
   polls-closed state) changed; otherwise the last update stands.
3. Results-only sources are parsed once for all their contests.
4. The Senate summary is published first and on its own, so nothing in the House
   or results-only path can stop it.

One race failing never stops the others: its last good update keeps being published,
and its own `as_of` shows how old it is. Two guards protect the published numbers:
- Before a state's polls close, its counts are test data (Minnesota's files already
  carried some in October) and the race is published as waiting.
- Once votes exist, a modeled race's configured D and R ballot names must both
  appear in the feed. If one is missing, the candidate map is wrong, and publishing
  would hand that side's votes to "other"; the race keeps its last good update instead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import signal
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Callable

from . import adapters as registry
from . import config as configuration
from . import districts, publish, results_only
from .adapters.fl_dos import BatchTracker
from .candidates import CandidateMap
from .config import Config, FeedConfig, RaceConfig, Results, ResultsSource
from .http import PoliteClient
from .model.simulate import RaceModel, RacePrior
from .replay import harness
from .schema import Snapshot

log = logging.getLogger("torehancast.poller")

DEFAULT_INTERVAL = 20.0  # seconds; the data bucket's cache max-age is 20s too
RESULTS_INTERVAL = 60.0  # results-only sources change the page less; poll them gently
FETCH_WORKERS = 8
FETCH_DEADLINE = 12.0  # seconds a cycle waits for its downloads
SEED = 0  # fixed, so an unchanged feed republishes identical numbers


def source_key(feed: FeedConfig) -> tuple:
    """Two races with the same download share one fetch."""
    return feed.adapter, feed.url, feed.election_id, tuple(sorted(feed.params.items()))


def digest(document) -> str:
    """A fingerprint of a fetched document, to tell whether anything changed."""
    if isinstance(document, str):
        document = document.encode()
    if not isinstance(document, bytes):
        document = json.dumps(document, sort_keys=True, default=repr).encode()
    return hashlib.sha256(document).hexdigest()


@dataclass
class _Source:
    document: object = None
    digest: str | None = None
    due: float = 0.0  # monotonic time of the next fetch
    future: Future | None = None


@dataclass
class _Race:
    key: tuple  # what the model was built from; a config change rebuilds it
    model: RaceModel
    tracker: BatchTracker | None  # Florida only: one per race for the whole night
    last: publish.StateUpdate | None = None
    seen: tuple | None = None  # (document, config, polls closed) behind `last`


@dataclass
class _Results:
    seen: tuple
    updates: list[publish.ResultsOnlyUpdate]


@dataclass
class Poller:
    writer: object
    config_dir: Path = configuration.DEFAULT_CONFIG_DIR
    client: PoliteClient | None = None
    adapter: Callable[[str], ModuleType] = registry.get
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    n_draws: int = 4000
    house_draws: int = 2000
    gate: str = "first_votes"
    fetch_deadline: float = FETCH_DEADLINE
    _config: Config | None = None
    _results: Results | None = None
    _races: dict[str, _Race] = field(default_factory=dict)
    _sources: dict[tuple, _Source] = field(default_factory=dict)
    _results_last: dict[str, _Results] = field(default_factory=dict)
    _pool: ThreadPoolExecutor = field(default_factory=lambda: ThreadPoolExecutor(FETCH_WORKERS))

    def cycle(self) -> None:
        started = time.monotonic()
        cfg = self._load_config()
        results = self._load_results(cfg)
        modeled = {rid: cfg.feeds[rid] for rid in cfg.races if cfg.feeds[rid].status == "ready"}
        ready_sources = {name: s for name, s in results.sources.items() if s.status == "ready"}
        # A race without a private prior isn't modeled (_poll says so), so don't download for it.
        wanted = {source_key(feed): (feed, 0.0) for rid, feed in modeled.items() if cfg.priors[rid] is not None}
        for source in ready_sources.values():
            wanted.setdefault(source_key(source.feed), (source.feed, RESULTS_INTERVAL))
        self._fetch(wanted)

        for race_id, feed in modeled.items():
            try:
                self._poll(race_id, cfg.races[race_id], feed, cfg.priors[race_id])
            except Exception as exc:  # one broken feed must not stop the others
                log.error("%s: %s: %s", race_id, type(exc).__name__, exc)
        updates: list[publish.Update] = [self._races[rid].last for rid in modeled
                                         if rid in self._races and self._races[rid].last is not None]
        for name, source in ready_sources.items():
            try:
                updates += self._results_for(name, source, results)
            except Exception as exc:  # its races keep their last good updates
                log.error("%s: %s: %s", name, type(exc).__name__, exc)
                if name in self._results_last:
                    updates += self._results_last[name].updates
        self._publish(updates)
        log.info("cycle %.1fs: %d sources, %d races", time.monotonic() - started, len(wanted), len(updates))

    def _load_config(self) -> Config:
        try:
            self._config = configuration.load_config(self.config_dir)
        except configuration.ConfigError as exc:
            if self._config is None:
                raise
            log.error("config invalid, keeping the previous one: %s", exc)
        return self._config

    def _load_results(self, cfg: Config) -> Results:
        # Loaded separately from the modeled config: a broken results file costs only
        # the results-only races, never the Senate.
        try:
            self._results = configuration.load_results(cfg, self.config_dir)
        except configuration.ConfigError as exc:
            log.error("results config invalid, keeping the previous one: %s", exc)
        return self._results or Results({}, {}, {})

    def _fetch(self, wanted: dict[tuple, tuple[FeedConfig, float]]) -> None:
        now = time.monotonic()
        for key in [k for k, s in self._sources.items() if k not in wanted and s.future is None]:
            del self._sources[key]  # no ready race uses it any more
        for key, (feed, every) in wanted.items():
            source = self._sources.setdefault(key, _Source())
            if source.future is None and now >= source.due:
                source.due = now + every
                source.future = self._pool.submit(self.adapter(feed.adapter).fetch_source, self.client, feed)
        running = [s.future for s in self._sources.values() if s.future is not None]
        wait(running, timeout=self.fetch_deadline)
        for key, source in self._sources.items():
            if source.future is None:
                continue
            if not source.future.done():
                log.warning("%s %s: still downloading after %.0fs; using its last document",
                            key[0], key[1] or key[2], self.fetch_deadline)
                continue
            future, source.future = source.future, None
            try:
                document = future.result()
            except Exception as exc:  # keep the last good document
                log.error("%s %s: fetch failed: %s: %s", key[0], key[1] or key[2], type(exc).__name__, exc)
                continue
            source.document, source.digest = document, digest(document)

    def _race(self, race_id: str, race: RaceConfig, prior: RacePrior, adapter: str) -> _Race:
        key = (race.baseline, race.tau_pair, race.unit, prior)
        current = self._races.get(race_id)
        if current is None or current.key != key:
            # A House race gets its own baseline, units and replay-tuned traits.
            model = harness.make_model(race_id, race.baseline, race.tau_pair, prior,
                                       harness.live_synthetic_split(race_id), race.unit)
            tracker = BatchTracker() if adapter == "fl_dos" else None
            last = current.last if current else None
            current = self._races[race_id] = _Race(key, model, tracker, last)
        return current

    def _poll(self, race_id: str, race: RaceConfig, feed: FeedConfig, prior: RacePrior | None) -> None:
        if prior is None:
            raise ValueError("ready feed but no private prior; not modeling this race")
        state = self._race(race_id, race, prior, feed.adapter)
        source = self._sources.get(source_key(feed))
        if source is None or source.digest is None:
            raise RuntimeError("no document fetched yet")
        now = self.clock()
        closed = now >= feed.polls_close_at
        seen = (source.digest, repr(feed), closed)
        if state.last is not None and state.seen == seen:
            return  # nothing changed: the last update stands, and the model isn't rerun
        snap = self.adapter(feed.adapter).parse(source.document, feed.contest, CandidateMap(feed.candidates), race_id)
        snap = harness.to_race_units(race_id, snap, race.unit)  # county parts for a district contest
        votes = sum(snap.totals().values())
        if not closed:
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
        draws = self.house_draws if race.race_type == "house" else self.n_draws
        result = state.model.run(snap, draws, SEED)
        as_of = snap.as_of or now.isoformat(timespec="seconds")
        state.last = publish.StateUpdate(race.state, race_id, dict(feed.display), result, state.model, as_of,
                                         votes=snap.totals(), race_type=race.race_type,
                                         district=districts.district_of(race_id),
                                         ranked_choice=race.ranked_choice)
        state.seen = seen

    def _results_for(self, name: str, source: ResultsSource, results: Results) -> list[publish.ResultsOnlyUpdate]:
        """One results-only source: every contest it serves, from one parse."""
        contests = [c for c in results.contests.values() if c.source == name]
        fetched = self._sources.get(source_key(source.feed))
        last = self._results_last.get(name)
        if fetched is None or fetched.digest is None:
            if last is None:
                raise RuntimeError("no document fetched yet")
            return last.updates
        now = self.clock()
        closed = now >= source.feed.polls_close_at
        seen = (fetched.digest, repr(source), repr(contests), closed)
        if last is not None and last.seen == seen:
            return last.updates
        parse_all = getattr(self.adapter(source.feed.adapter), "parse_all_contests", None)
        if parse_all is None:
            raise NotImplementedError(f"adapter {source.feed.adapter!r} has no parse_all_contests")
        found = parse_all(fetched.document, contests)
        if not closed:
            if votes := sum(sum(t.votes.values()) for t in found.values()):
                log.warning("%s: %d votes before polls close: treated as test data", name, votes)
            found = {}
        as_of = now.isoformat(timespec="seconds")
        updates = [results_only.update(c, source.state, found.get(c.race_id), as_of) for c in contests]
        self._results_last[name] = _Results(seen, updates)
        return updates

    def _publish(self, updates: list[publish.Update]) -> None:
        """Senate first and on its own; an update that can't be rendered is dropped, not fatal."""
        sound = []
        for u in updates:
            try:
                publish.state_detail(u, "live", self.gate)
            except Exception as exc:
                log.error("%s: not publishable: %s: %s", u.race, type(exc).__name__, exc)
            else:
                sound.append(u)
        senate = [u for u in sound if u.race_type != "house"]
        house = [u for u in sound if u.race_type == "house"]
        if not senate:
            # A summary with no races is invalid public JSON; leave the last one in place.
            log.warning("no ready Senate feed has produced an update; summary.json not published")
        for label, batch in (("senate", senate), ("house", house)):
            if not batch:
                continue
            try:
                publish.publish(batch, self.writer, mode="live", gate=self.gate)
            except Exception as exc:
                log.error("publishing %s failed: %s: %s", label, type(exc).__name__, exc)

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
    poller = Poller(writer, args.config_dir, PoliteClient(timeout=FETCH_DEADLINE), n_draws=args.draws, gate=args.gate)
    if args.once:
        poller.cycle()
    else:
        poller.run_forever(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
