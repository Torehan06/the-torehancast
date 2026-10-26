"""Every adapter named in config resolves through the registry and speaks the protocol."""

from pathlib import Path

import pytest

from torehancast import adapters, config, elections

ROOT = Path(__file__).resolve().parents[2]


def named_adapters() -> set[str]:
    loaded = config.load_config(ROOT / "config")
    results = config.load_results(loaded, ROOT / "config")
    named = {feed.adapter for feed in loaded.feeds.values()}
    named |= {source.feed.adapter for source in results.sources.values()}
    for state in {race.state for race in loaded.races.values()}:
        named |= {spec["adapter"] for spec in elections.specs(state).values()}
    return named - {None}


@pytest.mark.parametrize("name", sorted(named_adapters()))
def test_named_adapter_has_the_protocol(name):
    module = adapters.get(name)
    for function in adapters.REQUIRED:
        assert callable(getattr(module, function))


@pytest.mark.parametrize("name", ["no_such_state", "../http", "", "GA"])
def test_unknown_adapter_is_refused(name):
    with pytest.raises(NotImplementedError):
        adapters.get(name)
