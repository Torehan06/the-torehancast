"""Private poller configuration. Validate without fetching feeds or publishing values.

    python -m torehancast.config validate [--config-dir config/]

An unset prior or pending feed is valid draft configuration, not live readiness.
Load this directory each poll cycle so feed edits do not require a redeploy.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
import math
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

import yaml

from .model.simulate import RacePrior

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
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
    _choice(data["unit"], ("county", "county-part", "town", "house-district"), where)
    _choice(data["status"], ("todo", "done", "blocked", "dropped"), where)
    if type(data["priority"]) is not int or data["priority"] < 1:
        raise ConfigError("races entry: priority must be a positive integer")
    if type(data["ranked_choice"]) is not bool:
        raise ConfigError("races entry: ranked_choice must be a boolean")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="check structure; does not certify live readiness")
    validate.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args(argv)
    try:
        loaded = load_config(args.config_dir)
    except ConfigError as exc:
        print(f"invalid config: {exc}", file=sys.stderr)
        return 1
    unset = sum(prior is None for prior in loaded.priors.values())
    pending = sum(feed.status != "ready" for feed in loaded.feeds.values())
    print(f"Valid config: {len(loaded.races)} races; {unset} priors unset; {pending} feeds not ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
