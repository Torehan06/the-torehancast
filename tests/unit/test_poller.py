"""Poller guards: test data before polls close, broken candidate maps, failing feeds.

The fetch is faked with counts from the committed NC baseline, so these tests need no
network and no archives (they run in CI).
"""

from datetime import datetime, timezone
import gzip
import json
import threading
import logging
from pathlib import Path
import shutil

import pytest
import yaml

from torehancast import elections, poller, publish
from torehancast.results_only import ContestTotals
from torehancast.schema import Cell, Snapshot

ROOT = Path(__file__).resolve().parents[2]
RACE = "2026-NC-SEN"
BEFORE = datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc)  # 7:00 pm ET; NC closes 7:30
AFTER = datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc)
# Synthetic test values, not the private priors.
TEST_PRIOR = {"margin": 0.02, "margin_sd": 0.06, "turnout_ratio": 0.7, "turnout_sd": 0.1}


def edit(directory, name, change):
    path = directory / name
    document = yaml.safe_load(path.read_text())
    change(document)
    path.write_text(yaml.safe_dump(document))


@pytest.fixture
def config_dir(tmp_path):
    for name in ("races.yaml", "feeds.yaml", "priors.example.yaml"):
        shutil.copy(ROOT / "config" / name, tmp_path / name)
    priors = yaml.safe_load((tmp_path / "priors.example.yaml").read_text())
    priors["priors"][RACE] = TEST_PRIOR
    (tmp_path / "priors.yaml").write_text(yaml.safe_dump(priors))
    edit(tmp_path, "feeds.yaml", lambda d: d["feeds"][RACE].update(status="ready"))
    return tmp_path


def nc_counts(n_counties=20, sides=("D", "R", "other")) -> Snapshot:
    base = elections.read_baseline("NC", "2024_pres")
    units = sorted(base.unit_id.unique())[:n_counties]
    rows = base[base.unit_id.isin(units)]
    cells = [Cell(r.unit_id, r.vote_type, {s: int(getattr(r, s)) for s in sides}) for r in rows.itertuples()]
    return Snapshot("NC", RACE, "2026-11-04T01:00:00Z", cells, {u: 1.0 for u in units})


class FakeFeed:
    """A fake adapter: each fetch returns the next response, and a document parses as itself."""

    def __init__(self, *responses, contests=None):
        self.responses = list(responses)
        self.calls = []  # one entry per fetch_source
        self.parses = 0
        self.contests = contests  # parse_all_contests(document, contests) for results-only sources

    def fetch_source(self, client, feed):
        self.calls.append(feed.url)
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        return response

    def parse(self, document, contest, cmap, race):
        self.parses += 1
        return document

    def parse_all_contests(self, document, contests):
        if self.contests is None:
            raise NotImplementedError
        return self.contests(document, contests)


def make(config_dir, out, fetch, now, **options):
    clock = {"now": now}
    p = poller.Poller(publish.LocalWriter(out), config_dir, adapter=lambda name: fetch,
                      clock=lambda: clock["now"], n_draws=500, **options)
    return p, clock


def summary(out) -> dict:
    states = json.loads((out / "data/live/summary.json").read_text())["states"]
    return {s["race"]: s for s in states}


def test_counts_before_polls_close_are_test_data(config_dir, tmp_path, caplog):
    p, _ = make(config_dir, tmp_path / "out", FakeFeed(nc_counts()), BEFORE)
    with caplog.at_level(logging.WARNING):
        p.cycle()
    assert summary(tmp_path / "out")[RACE]["status"] == "waiting"
    assert "before polls close" in caplog.text
    detail = json.loads((tmp_path / "out/data/live/races/2026-NC-SEN.json").read_text())
    assert "votes" not in detail and "p_win" not in detail


def test_counts_after_polls_close_are_published(config_dir, tmp_path):
    snap = nc_counts()
    p, _ = make(config_dir, tmp_path / "out", FakeFeed(snap), AFTER)
    p.cycle()
    race = summary(tmp_path / "out")[RACE]
    assert race["status"] == "live" and race["modeled"] is True
    assert race["candidates"] == {"D": "Roy Cooper", "R": "Michael Whatley"}
    assert race["votes"] == {"D": snap.totals()["D"], "R": snap.totals()["R"]}
    assert set(race["p_win"]) == {"D", "R"}


def test_missing_candidate_keeps_last_good_update(config_dir, tmp_path, caplog):
    good = nc_counts(10)
    broken = nc_counts(30, sides=("R", "other"))  # D's ballot name no longer matches
    p, _ = make(config_dir, tmp_path / "out", FakeFeed(good, broken), AFTER)
    p.cycle()
    with caplog.at_level(logging.ERROR):
        p.cycle()
    assert summary(tmp_path / "out")[RACE]["votes"]["D"] == good.totals()["D"]
    assert "no ['D'] ballot name" in caplog.text


def test_failing_feed_keeps_last_good_update(config_dir, tmp_path, caplog):
    good = nc_counts(10)
    p, _ = make(config_dir, tmp_path / "out", FakeFeed(good, TimeoutError("state server timed out")), AFTER)
    p.cycle()
    with caplog.at_level(logging.ERROR):
        p.cycle()
    race = summary(tmp_path / "out")[RACE]
    assert race["votes"]["R"] == good.totals()["R"]
    assert race["as_of"] == good.as_of  # the page sees how old it is
    assert "TimeoutError" in caplog.text


def test_invalid_config_mid_night_keeps_previous_config(config_dir, tmp_path, caplog):
    p, _ = make(config_dir, tmp_path / "out", FakeFeed(nc_counts()), AFTER)
    p.cycle()
    (config_dir / "feeds.yaml").write_text("feeds: [broken")
    with caplog.at_level(logging.ERROR):
        p.cycle()
    assert summary(tmp_path / "out")[RACE]["status"] == "live"
    assert "keeping the previous one" in caplog.text


def test_only_ready_feeds_are_polled(config_dir, tmp_path):
    edit(config_dir, "feeds.yaml", lambda d: d["feeds"][RACE].update(status="pending"))
    fetch = FakeFeed(nc_counts())
    p, _ = make(config_dir, tmp_path / "out", fetch, AFTER)
    p.cycle()
    assert fetch.calls == []
    assert not (tmp_path / "out/data/live/summary.json").exists()  # never an empty summary


def test_ready_feed_without_prior_is_not_modeled(config_dir, tmp_path, caplog):
    edit(config_dir, "priors.yaml", lambda d: d["priors"].update({RACE: None}))
    p, _ = make(config_dir, tmp_path / "out", FakeFeed(nc_counts()), AFTER)
    with caplog.at_level(logging.ERROR):
        p.cycle()
    assert not (tmp_path / "out/data/live/summary.json").exists()
    assert "no private prior" in caplog.text


def test_florida_tracker_never_sees_test_data(config_dir, tmp_path):
    fl = "2026-FL-SEN-SPECIAL"

    def ready(d):
        d["feeds"][fl].update(status="ready", election_id="2026-11-03", contest="USS",
                              candidates={"Angie Nixon": "D", "Ashley Moody": "R"})

    edit(config_dir, "feeds.yaml", ready)
    edit(config_dir, "priors.yaml", lambda d: d["priors"].update({fl: TEST_PRIOR}))
    test_data = Snapshot("FL", fl, None, [Cell("ALACHUA", "all", {"D": 900, "R": 800})], {"ALACHUA": 0.0})
    p, _ = make(config_dir, tmp_path / "out", FakeFeed(test_data), datetime(2026, 11, 3, 23, 0, tzinfo=timezone.utc))
    p.cycle()  # 6 pm ET, an hour before Florida's first polls close
    assert p._races[fl].tracker.early == {}


def with_nc_house_results(config_dir):
    """NC's House districts as results-only races, read from the Senate's own download."""
    (config_dir / "results").mkdir()
    shutil.copy(ROOT / "config" / "results" / "NC.yaml", config_dir / "results" / "NC.yaml")
    edit(config_dir / "results", "NC.yaml", lambda d: d["results"]["sources"]["sbe"].update(status="ready"))


def house_totals(document, contests):
    return {c.race_id: ContestTotals({"D": "Dem", "R": "Rep"}, {"D": 600, "R": 400}, 0.5) for c in contests[:3]}


def house(out) -> dict:
    return {r["race"]: r for r in json.loads((out / "data/live/house.json").read_text())["races"]}


def test_one_download_serves_the_senate_and_every_house_contest(config_dir, tmp_path):
    with_nc_house_results(config_dir)
    fetch = FakeFeed(nc_counts(), contests=house_totals)
    p, _ = make(config_dir, tmp_path / "out", fetch, AFTER)
    p.cycle()
    assert len(fetch.calls) == 1
    assert summary(tmp_path / "out")[RACE]["status"] == "live"
    races = house(tmp_path / "out")
    assert len(races) == 12  # NC-1 and NC-11 are modeled, not results-only
    assert races["2026-NC-H02"]["votes"] == {"D": 600, "R": 400} and races["2026-NC-H02"]["modeled"] is False
    assert races["2026-NC-H14"]["status"] == "waiting"  # not in the feed yet: no votes
    assert not (tmp_path / "out/data/live/races/2026-NC-H02.json").exists()


def test_results_only_counts_before_polls_close_are_test_data(config_dir, tmp_path, caplog):
    with_nc_house_results(config_dir)
    p, _ = make(config_dir, tmp_path / "out", FakeFeed(nc_counts(), contests=house_totals), BEFORE)
    with caplog.at_level(logging.WARNING):
        p.cycle()
    assert {r["status"] for r in house(tmp_path / "out").values()} == {"waiting"}
    assert "NC/sbe: 3000 votes before polls close" in caplog.text


def test_a_broken_results_source_never_blocks_the_senate(config_dir, tmp_path, caplog):
    with_nc_house_results(config_dir)

    def broken(document, contests):
        raise ValueError("unexpected layout")

    p, _ = make(config_dir, tmp_path / "out", FakeFeed(nc_counts(), contests=broken), AFTER)
    with caplog.at_level(logging.ERROR):
        p.cycle()
    assert summary(tmp_path / "out")[RACE]["status"] == "live"
    assert not (tmp_path / "out/data/live/house.json").exists()
    assert "NC/sbe: ValueError: unexpected layout" in caplog.text


def test_a_broken_results_file_never_blocks_the_senate(config_dir, tmp_path, caplog):
    with_nc_house_results(config_dir)
    (config_dir / "results" / "NC.yaml").write_text("results: [broken")
    p, _ = make(config_dir, tmp_path / "out", FakeFeed(nc_counts(), contests=house_totals), AFTER)
    with caplog.at_level(logging.ERROR):
        p.cycle()
    assert summary(tmp_path / "out")[RACE]["status"] == "live"
    assert "results config invalid" in caplog.text


def test_an_unchanged_document_does_not_rerun_the_model(config_dir, tmp_path):
    fetch = FakeFeed(nc_counts(10), nc_counts(10), nc_counts(20))
    p, _ = make(config_dir, tmp_path / "out", fetch, AFTER)
    p.cycle()
    p.cycle()
    assert fetch.parses == 1 and len(fetch.calls) == 2
    p.cycle()
    assert fetch.parses == 2
    assert summary(tmp_path / "out")[RACE]["votes"]["D"] == nc_counts(20).totals()["D"]


def test_polls_closing_reruns_an_unchanged_document(config_dir, tmp_path):
    p, clock = make(config_dir, tmp_path / "out", FakeFeed(nc_counts()), BEFORE)
    p.cycle()
    assert summary(tmp_path / "out")[RACE]["status"] == "waiting"
    clock["now"] = AFTER
    p.cycle()
    assert summary(tmp_path / "out")[RACE]["status"] == "live"


def test_a_slow_download_is_picked_up_by_a_later_cycle(config_dir, tmp_path, caplog):
    release = threading.Event()

    class Slow(FakeFeed):
        def fetch_source(self, client, feed):
            release.wait(5)
            return super().fetch_source(client, feed)

    p, _ = make(config_dir, tmp_path / "out", Slow(nc_counts()), AFTER, fetch_deadline=0.05)
    with caplog.at_level(logging.WARNING):
        p.cycle()
    assert "still downloading" in caplog.text
    assert not (tmp_path / "out/data/live/summary.json").exists()
    release.set()
    p.fetch_deadline = 5
    p.cycle()
    assert summary(tmp_path / "out")[RACE]["status"] == "live"


class FakeBlob:
    def __init__(self, store, key):
        self.store, self.key, self.cache_control, self.content_encoding = store, key, None, None

    def upload_from_string(self, body, content_type):
        self.store[self.key] = (body, content_type, self.cache_control, self.content_encoding)


class FakeGCS:
    def __init__(self):
        self.store = {}

    def bucket(self, name):
        return self

    def blob(self, key):
        return FakeBlob(self.store, key)


@pytest.mark.parametrize("key", ["config/priors.yaml", "data/../config/feeds.yaml", "/data/live/x.json", "datax/y"])
def test_gcs_writer_refuses_keys_outside_data(key):
    gcs = FakeGCS()
    with pytest.raises(ValueError):
        publish.GCSWriter("bucket", client=gcs).write(key, {})
    assert gcs.store == {}


def test_gcs_writer_sets_short_public_cache():
    gcs = FakeGCS()
    publish.GCSWriter("bucket", client=gcs).write("data/live/summary.json", {"a": 1})
    body, content_type, cache, encoding = gcs.store["data/live/summary.json"]
    assert json.loads(gzip.decompress(body)) == {"a": 1} and encoding == "gzip"
    assert content_type == "application/json" and cache == "public, max-age=20"


def test_gcs_writer_skips_an_unchanged_body():
    gcs = FakeGCS()
    writer = publish.GCSWriter("bucket", client=gcs)
    writer.write_many([("data/live/races/a.json", {"a": 1}), ("data/live/races/b.json", {"b": 1})])
    gcs.store.clear()
    writer.write_many([("data/live/races/a.json", {"a": 1}), ("data/live/races/b.json", {"b": 2})])
    assert set(gcs.store) == {"data/live/races/b.json"}


def test_gcs_writer_refuses_a_batch_with_one_bad_key():
    gcs = FakeGCS()
    with pytest.raises(ValueError):
        publish.GCSWriter("bucket", client=gcs).write_many([("data/live/a.json", {}), ("config/priors.yaml", {})])
    assert gcs.store == {}
