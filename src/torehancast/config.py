"""Private poller configuration. Validate without fetching feeds or publishing values.

    python -m torehancast.config validate [--config-dir config/]

An unset prior or pending feed is valid draft configuration, not live readiness.
Load this directory each poll cycle so feed edits do not require a redeploy.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field, replace
from datetime import datetime
import math
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

import yaml

from . import districts
from .model.simulate import RacePrior

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
RCV_STATES = frozenset({"ME", "AK"})  # ranked-choice federal general elections
STATES = frozenset("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())


class ConfigError(ValueError):
    """Invalid poller config; messages describe fields, never private values."""


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            if key in result:
                raise ConfigError("duplicate YAML key")
            result[key] = loader.construct_object(value_node, deep=True)
        except TypeError:
            raise ConfigError("YAML keys must be strings") from None
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


@dataclass(frozen=True)
class RaceConfig:
    state: str
    race_type: str
    unit: str
    priority: int
    baseline: str
    ranked_choice: bool
    status: str
    fallback_baseline: str | None = None
    # Historical pair the live county scatter (tau) is measured on, e.g. 2020_sen → 2022_sen.
    tau_pair: tuple[str, str] | None = None
    notes: str = ""


@dataclass(frozen=True)
class FeedConfig:
    adapter: str | None
    url: str | None
    election_id: str | None
    status: str
    params: dict[str, str] = field(default_factory=dict)
    reference_url: str | None = None
    # Live contest as the feed names it, and exact feed ballot name → side ("D", "R").
    contest: str | None = None
    candidates: dict[str, str] = field(default_factory=dict)
    # Side → name shown on the dashboard. Every display side must appear in `candidates`.
    display: dict[str, str] = field(default_factory=dict)
    # Earliest poll closing in the state (ISO 8601 with offset). Counts seen before it
    # are treated as test data and never published.
    polls_close: str | None = None
    notes: str = ""

    @property
    def polls_close_at(self) -> datetime | None:
        return datetime.fromisoformat(self.polls_close) if self.polls_close else None


@dataclass(frozen=True)
class Config:
    races: dict[str, RaceConfig]
    feeds: dict[str, FeedConfig]
    priors: dict[str, RacePrior | None] = field(repr=False)


def _mapping(value, where: str) -> dict:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ConfigError(f"{where}: expected a mapping with string keys")
    return value


def _fields(value, required: set[str], optional: set[str], where: str) -> dict:
    value = _mapping(value, where)
    if required - value.keys() or value.keys() - required - optional:
        raise ConfigError(f"{where}: missing or unknown fields")
    return value


def _text(value, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}: expected nonempty text")
    return value


def _choice(value, choices: tuple[str, ...], where: str):
    if not isinstance(value, str) or value not in choices:
        raise ConfigError(f"{where}: unsupported value")


def _document(path: Path, section: str) -> dict:
    try:
        doc = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueLoader)
    except ConfigError as exc:
        raise ConfigError(f"{path.name}: {exc}") from None
    except (OSError, UnicodeError):
        raise ConfigError(f"{path.name}: cannot read config file") from None
    except (yaml.YAMLError, ValueError, RecursionError):
        # Parser exceptions can include the source line and therefore a secret.
        raise ConfigError(f"{path.name}: invalid YAML") from None
    return _mapping(_fields(doc, {section}, set(), path.name)[section], path.name)


def _race(race_id: str, raw) -> RaceConfig:
    where = "races entry"
    data = _fields(raw, {"state", "race_type", "unit", "priority", "baseline", "ranked_choice", "status"},
                   {"fallback_baseline", "tau_pair", "notes"}, where)
    if not re.fullmatch(r"\d{4}-[A-Z]{2}-[A-Z0-9]+(?:-[A-Z0-9]+)*", race_id):
        raise ConfigError("races: invalid race ID")
    if not isinstance(data["state"], str) or data["state"] not in STATES or race_id.split("-")[1] != data["state"]:
        raise ConfigError("races entry: state must match race ID")
    _choice(data["race_type"], ("senate", "senate-special", "house", "governor"), where)
    if (data["race_type"] == "house") != (districts.parse_house_race_id(race_id) is not None):
        raise ConfigError("races entry: house races need a 2026-XX-HNN (or -HAL) ID for a real district")
    _choice(data["unit"], ("county", "county-part", "town", "house-district"), where)
    _choice(data["status"], ("todo", "done", "blocked", "dropped"), where)
    if type(data["priority"]) is not int or data["priority"] < 1:
        raise ConfigError("races entry: priority must be a positive integer")
    if type(data["ranked_choice"]) is not bool:
        raise ConfigError("races entry: ranked_choice must be a boolean")
    if data["state"] in RCV_STATES and data["race_type"] != "governor" and not data["ranked_choice"]:
        # The publisher's RCV fail-closed path keys on this flag.
        raise ConfigError("races entry: ME and AK federal races are ranked-choice")
    _text(data["baseline"], "races entry: baseline")
    for key in ("fallback_baseline", "notes"):
        if key in data:
            _text(data[key], f"races entry: {key}")
    if "tau_pair" in data:
        pair = data["tau_pair"]
        if not isinstance(pair, list) or len(pair) != 2:
            raise ConfigError("races entry: tau_pair must list two election keys")
        data["tau_pair"] = tuple(_text(key, "races entry: tau_pair") for key in pair)
    return RaceConfig(**data)


def _url(value, where: str):
    if value is None:
        return
    _text(value, where)
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname and not parsed.username
                 and not parsed.password and not parsed.fragment and not any(c.isspace() for c in value))
        parsed.port  # reject invalid ports as well
    except ValueError:
        valid = False
    if not valid:
        raise ConfigError(f"{where}: expected an HTTPS URL without credentials or fragments")


def _names(value, where: str) -> dict[str, str]:
    value = _mapping(value, where)
    for key, name in value.items():
        _text(key, where)
        _text(name, where)
    return value


def _feed(raw) -> FeedConfig:
    data = _fields(raw, {"adapter", "url", "election_id", "status"},
                   {"params", "reference_url", "contest", "candidates", "display", "polls_close", "notes"},
                   "feeds entry")
    _choice(data["status"], ("pending", "ready", "blocked", "dropped"), "feeds entry: status")
    for key in ("adapter", "election_id", "notes"):
        if data.get(key) is not None:
            _text(data[key], f"feeds entry: {key}")
    if data["adapter"] is not None and not re.fullmatch(r"[a-z][a-z0-9_]*", data["adapter"]):
        raise ConfigError("feeds entry: invalid adapter name")
    for key in ("url", "reference_url"):
        _url(data.get(key), f"feeds entry: {key}")
    params = _mapping(data.get("params", {}), "feeds entry: params")
    if any(not isinstance(value, str) for value in params.values()):
        raise ConfigError("feeds entry: params values must be strings")
    if data.get("contest") is not None:
        _text(data["contest"], "feeds entry: contest")
    candidates = _names(data.get("candidates") or {}, "feeds entry: candidates")
    display = _names(data.get("display") or {}, "feeds entry: display")
    if set(display) - set(candidates.values()) and candidates:
        raise ConfigError("feeds entry: every display side must be a side in candidates")
    if data.get("polls_close") is not None:
        try:
            closes = datetime.fromisoformat(_text(data["polls_close"], "feeds entry: polls_close"))
        except ValueError:
            closes = None
        if closes is None or closes.utcoffset() is None:
            raise ConfigError("feeds entry: polls_close must be ISO 8601 with a UTC offset")
    if data["status"] == "ready":
        if any(data[key] is None for key in ("adapter", "url", "election_id")):
            raise ConfigError("feeds entry: ready feeds require adapter, url and election_id")
        if data.get("contest") is None or data.get("polls_close") is None or not {"D", "R"} <= set(display):
            raise ConfigError("feeds entry: ready feeds require contest, polls_close and D/R display names")
        if not {"D", "R"} <= set(candidates.values()):
            raise ConfigError("feeds entry: ready feeds must map ballot names to both D and R")
    return FeedConfig(**{**data, "candidates": candidates, "display": display})


def _prior(raw) -> RacePrior | None:
    if raw is None:
        return None
    data = _fields(raw, {"margin", "margin_sd", "turnout_ratio", "turnout_sd"}, set(), "priors entry")
    for key, value in data.items():
        try:
            finite = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ConfigError(f"priors entry: {key} must be a finite number")
        if key == "margin":
            if not -1 <= value <= 1:
                raise ConfigError("priors entry: margin must be between -1 and 1")
        elif value <= 0:
            raise ConfigError(f"priors entry: {key} must be positive")
    return RacePrior(**data)


def _same_races(entries: dict, races: dict, name: str):
    if entries.keys() != races.keys():
        raise ConfigError(f"{name}: race IDs must exactly match races.yaml")


def load_config(directory: Path = DEFAULT_CONFIG_DIR) -> Config:
    """Read a complete config snapshot; never write files or make network requests.

    The example is always validated but never supplies runtime priors. A private
    file must list every race; omission must be explicit (null).
    """
    directory = Path(directory)
    races = {key: _race(key, value) for key, value in _document(directory / "races.yaml", "races").items()}
    if not races:
        raise ConfigError("races.yaml: registry must not be empty")
    feeds = _document(directory / "feeds.yaml", "feeds")
    _same_races(feeds, races, "feeds.yaml")
    feeds = {key: _feed(value) for key, value in feeds.items()}
    if any(feeds[key].status == "ready" and races[key].tau_pair is None for key in races):
        raise ConfigError("races.yaml: a race with a ready feed needs tau_pair")
    example = _document(directory / "priors.example.yaml", "priors")
    _same_races(example, races, "priors.example.yaml")
    for value in example.values():
        _prior(value)
    priors = dict.fromkeys(races)
    private = directory / "priors.yaml"
    try:
        private.lstat()  # A dangling symlink is an invalid file, not an absent one.
    except FileNotFoundError:
        pass
    except OSError:
        raise ConfigError("priors.yaml: cannot read config file") from None
    else:
        values = _document(private, "priors")
        _same_races(values, races, "priors.yaml")
        priors = {key: _prior(value) for key, value in values.items()}
    return Config(races, feeds, priors)


# Results-only registry: config/results/<ST>.yaml. Vote totals only (no model, no prior),
# loaded separately from load_config so a broken results file never blocks the Senate.

@dataclass(frozen=True)
class ResultsSource:
    """One download that serves many contests. `same_as` borrows a modeled race's feed."""
    state: str
    name: str
    status: str
    feed: FeedConfig  # resolved: the modeled race's feed when `same_as` is set
    same_as: str | None = None


@dataclass(frozen=True)
class ResultsContest:
    race_id: str
    race_type: str
    district: int | None
    source: str  # "<ST>/<source name>"
    # The contest as the feed names it (template filled in); None until verified.
    contest: str | None = None
    # Exact ballot name → side key, where the feed's party labels aren't enough.
    sides: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Results:
    sources: dict[str, ResultsSource]
    contests: dict[str, ResultsContest]
    none: dict[str, str]  # race ID → why it has no results feed


_INHERITED = ("adapter", "url", "election_id", "params", "reference_url", "polls_close")


def _sides(value, where: str) -> dict[str, str]:
    """Ballot name → side key for a results-only contest; the publisher keys candidates by it."""
    sides = _names(value, where)
    # A party letter plus an optional digit for a second candidate of that party (D2 in a
    # same-party top-two), or "other". Several names may pool into "other"; named keys are
    # one candidate each, and at most five are published.
    named = [side for side in sides.values() if side != "other"]
    if any(not re.fullmatch(r"[A-Z][2-9]?", side) for side in named):
        raise ConfigError(f"{where}: side keys are a capital party letter, an optional digit, or other")
    if len(named) != len(set(named)):
        raise ConfigError(f"{where}: each named side key belongs to one candidate")
    if len(named) > 5:
        raise ConfigError(f"{where}: at most 5 named candidates; pool the rest into other")
    return sides


def _template(value, district: int | None, where: str) -> str | None:
    if value is None:
        return None
    _text(value, where)
    try:
        filled = value.format(n=district) if district is not None else value.format()
    except (KeyError, IndexError, ValueError, AttributeError):
        raise ConfigError(f"{where}: template may use only {{n}} (House) or nothing (Senate)") from None
    return filled


def _results_contests(state: str, source: str, raw, modeled: dict[str, RaceConfig]) -> list[ResultsContest]:
    where = f"results/{state}.yaml: {source}"
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{where}: contests must be a nonempty list")
    contests = []
    for entry in raw:
        data = _fields(entry, {"office"}, {"template", "districts", "sides", "notes"}, f"{where} contest")
        _choice(data["office"], ("senate", "house"), f"{where} contest: office")
        sides = _sides(data.get("sides") or {}, f"{where} contest: sides")
        if data["office"] == "senate":
            if "districts" in data:
                raise ConfigError(f"{where}: a Senate contest has no districts")
            try:
                race_id = districts.senate_race_id(state)
            except ValueError:
                raise ConfigError(f"{where}: {state} has no {districts.YEAR} Senate race") from None
            if race_id in modeled:
                raise ConfigError(f"{where}: {race_id} is modeled; it can't also be results-only")
            race_type = "senate-special" if state in districts.SENATE_SPECIALS else "senate"
            contests.append(ResultsContest(race_id, race_type, None, f"{state}/{source}",
                                           _template(data.get("template"), None, where), sides))
            continue
        seats = districts.APPORTIONMENT[state]
        wanted = data.get("districts")
        if wanted == "all":  # every district that isn't modeled
            numbers = [n for n in range(1, seats + 1) if districts.house_race_id(state, n) not in modeled]
        elif isinstance(wanted, list) and wanted and all(type(n) is int for n in wanted):
            numbers = wanted
        else:
            raise ConfigError(f"{where}: districts must be `all` or a list of district numbers")
        for n in numbers:
            try:
                race_id = districts.house_race_id(state, n)
            except ValueError:
                raise ConfigError(f"{where}: {state} has no district {n}") from None
            if race_id in modeled:
                raise ConfigError(f"{where}: {race_id} is modeled; it can't also be results-only")
            contests.append(ResultsContest(race_id, "house", n, f"{state}/{source}",
                                           _template(data.get("template"), n, where), sides))
    filled = [c.contest for c in contests if c.contest is not None]
    if len(filled) != len(set(filled)):
        raise ConfigError(f"{where}: two contests share one name; does the House template use {{n}}?")
    return contests


def _results_source(state: str, name: str, raw, config: Config) -> tuple[ResultsSource, list[ResultsContest]]:
    where = f"results/{state}.yaml: {name}"
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ConfigError(f"results/{state}.yaml: source names are lowercase identifiers")
    data = _fields(raw, {"status", "contests"}, {"same_as", "notes", *_INHERITED}, where)
    _choice(data["status"], ("pending", "ready", "blocked", "dropped"), f"{where}: status")
    same_as = data.get("same_as")
    if same_as is not None:
        if same_as not in config.feeds or config.races[same_as].state != state:
            raise ConfigError(f"{where}: same_as must name a modeled race in {state}")
        if any(key in data for key in _INHERITED):
            raise ConfigError(f"{where}: a same_as source inherits its feed settings; don't repeat them")
        base = config.feeds[same_as]
        feed = FeedConfig(base.adapter, base.url, base.election_id, data["status"], base.params,
                          base.reference_url, polls_close=base.polls_close)
    else:
        # Reuse the modeled-feed checks; the D/R rules don't apply because nothing is modeled here.
        feed = _feed({key: data.get(key) for key in ("adapter", "url", "election_id")}
                     | {key: data[key] for key in ("params", "reference_url", "polls_close") if key in data}
                     | {"status": "pending"})
        feed = replace(feed, status=data["status"])
    contests = _results_contests(state, name, data["contests"], config.races)
    if data["status"] == "ready":
        if feed.adapter is None or feed.url is None or feed.polls_close is None:
            raise ConfigError(f"{where}: ready sources require adapter, url and polls_close")
        if any(c.contest is None for c in contests):
            raise ConfigError(f"{where}: ready sources require a template for every contest")
    return ResultsSource(state, name, data["status"], feed, same_as), contests


def _none(state: str, raw, covered: set[str], modeled: dict[str, RaceConfig]) -> dict[str, str]:
    """`senate` / `house` mean every such race in the state not modeled or results-only."""
    where = f"results/{state}.yaml: none"
    result = {}
    for key, reason in _mapping(raw, where).items():
        reason = _text(reason, f"{where}: reason")
        if key == "senate":
            try:
                ids = [districts.senate_race_id(state)]
            except ValueError:
                raise ConfigError(f"{where}: {state} has no {districts.YEAR} Senate race") from None
            if ids[0] in covered or ids[0] in modeled:
                raise ConfigError(f"{where}: the {state} Senate race already has a source")
        elif key == "house":
            ids = [districts.house_race_id(state, n) for n in range(1, districts.APPORTIONMENT[state] + 1)]
            ids = [i for i in ids if i not in covered and i not in modeled]
        else:
            if districts.parse_house_race_id(key) is None or not key.split("-")[1] == state:
                raise ConfigError(f"{where}: keys are senate, house or a {state} House race ID")
            if key in covered or key in modeled:
                raise ConfigError(f"{where}: {key} already has a source")
            ids = [key]
        for race_id in ids:
            result.setdefault(race_id, reason)  # an explicit ID wins over the `house` catch-all
    return result


def load_results(config: Config, directory: Path = DEFAULT_CONFIG_DIR) -> Results:
    """Read config/results/<ST>.yaml. Raises ConfigError; never touches the modeled config."""
    sources, contests, none = {}, {}, {}
    folder = Path(directory) / "results"
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        state = path.stem
        if state not in districts.APPORTIONMENT:
            raise ConfigError(f"results/{path.name}: file name must be a state code")
        doc = _document(path, "results")
        data = _fields(doc, {"sources"}, {"none"}, f"results/{path.name}")
        state_contests = []
        for name, raw in _mapping(data["sources"] or {}, f"results/{path.name}: sources").items():
            source, found = _results_source(state, name, raw, config)
            sources[f"{state}/{name}"] = source
            state_contests += found
        ids = [c.race_id for c in state_contests]
        if len(ids) != len(set(ids)):
            raise ConfigError(f"results/{path.name}: a race is listed by more than one contest")
        contests.update((c.race_id, c) for c in state_contests)
        none.update(_none(state, data.get("none") or {}, set(ids), config.races))
    return Results(sources, contests, none)


def coverage(config: Config, results: Results) -> dict[str, str]:
    """Race ID → "modeled", "results" or "none" for every race the config knows about."""
    return ({race_id: "none" for race_id in results.none}
            | {race_id: "results" for race_id in results.contests}
            | {race_id: "modeled" for race_id in config.races})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="check structure; does not certify live readiness")
    validate.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args(argv)
    try:
        loaded = load_config(args.config_dir)
        results = load_results(loaded, args.config_dir)
    except ConfigError as exc:
        print(f"invalid config: {exc}", file=sys.stderr)
        return 1
    unset = sum(prior is None for prior in loaded.priors.values())
    pending = sum(feed.status != "ready" for feed in loaded.feeds.values())
    print(f"Valid config: {len(loaded.races)} races; {unset} priors unset; {pending} feeds not ready.")
    federal = set(districts.senate_race_ids()) | set(districts.house_race_ids())
    uncovered = len(federal - coverage(loaded, results).keys())
    waiting = sum(source.status != "ready" for source in results.sources.values())
    print(f"Results-only: {len(results.contests)} races from {len(results.sources)} sources "
          f"({waiting} not ready); {len(results.none)} with no feed; {uncovered} not registered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
