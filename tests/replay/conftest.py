"""`pytest tests/replay --state NC` runs exactly one state's replay checks.

(`-k NC` can't do this: "acceptance" contains "nc", so it matches every test.)
"""


def pytest_addoption(parser):
    parser.addoption("--state", default=None, help="only run replay tests for this state, e.g. --state NC")


def pytest_collection_modifyitems(config, items):
    state = config.getoption("--state")
    if not state:
        return
    keep, drop = [], []
    for item in items:
        params = getattr(getattr(item, "callspec", None), "params", {})
        states = {v[0] for v in params.values() if isinstance(v, tuple) and len(v) == 2}
        (keep if state.upper() in states else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
    items[:] = keep

