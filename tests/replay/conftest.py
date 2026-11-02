"""Pick replays by state or by race:

    pytest tests/replay --state NC          # the state's Senate-style replays (replay.yaml)
    pytest tests/replay --race 2026-IA-H01  # one House district's replays (config/house/)

`--race` takes a Senate race ID too (2026-GA-SEN means --state GA). Both options
together run the union. (`-k NC` can't do this: "acceptance" contains "nc", so it
matches every test.)
"""

from torehancast.replay import harness


def pytest_addoption(parser):
    parser.addoption("--state", default=None, help="only run replay tests for this state, e.g. --state NC")
    parser.addoption("--race", default=None, help="only run replay tests for this race, e.g. --race 2026-IA-H01")


def pytest_collection_modifyitems(config, items):
    state, race = config.getoption("--state"), config.getoption("--race")
    if not state and not race:
        return
    wanted = {k for k in (state and state.upper(), race and harness.resolve(race.upper())) if k}
    keep, drop = [], []
    for item in items:
        params = getattr(getattr(item, "callspec", None), "params", {})
        keys = {v[0] for v in params.values() if isinstance(v, tuple) and len(v) == 2}
        (keep if wanted & keys else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
    items[:] = keep
