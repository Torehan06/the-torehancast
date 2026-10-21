"""Check public artifact shapes and accidental copies of private config values.

This verifies public artifact shapes and private-input copies, not posterior independence.
Historical replay priors are intentionally public; live private priors are not.

Value scan, decided with Törehan on Oct 21 (the release gate):

- Numbers inside a race entry are compared only with its own race's prior values that
  have 4 or more decimals. Hand-entered priors have 1-3 (0.1, 0.07, -0.045), and a
  night's thousands of published probabilities, margins and county shares match such
  values by chance: simulated election nights raised a false alarm ~100% of the time
  (80% even with county tables skipped). A copied 0.1 can't be told from a chance 0.1,
  so the check looks only where a match means a copy. The CI canary priors (7 decimals)
  run through the real publisher and prove the code never copies a prior.
- Text anywhere (names, timestamps, file names) is compared with every non-integer
  prior value; numbers outside race entries with every prior value and rounding.
- Skipped, because they can't carry a prior: identity fields (`state`, `race`,
  `race_type`, `district`) once shown to agree, raw vote counts, and `vote_share`
  values equal to the share recomputed from those counts.

Key names, file names and types, the waiting shape and live prior coverage are always checked.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from . import districts
from .elections import CONFIG

RACE_TYPES = {"senate", "senate-special", "house"}
PRECISE_DECIMALS = 4  # a prior value this precise can't match a published number by chance


class PublicJSONError(ValueError):
    pass


@dataclass(frozen=True)
class ScanReport:
    files: int
    private_values_checked: bool


def _require(ok: bool, where: str) -> None:
    if not ok:
        raise PublicJSONError("invalid public payload; path and contents withheld")


def _shape(value, keys: set[str], required: set[str], where: str) -> None:
    _require(isinstance(value, dict) and required <= value.keys() <= keys, where)


def _number(value, where: str, lo: float = -math.inf, hi: float = math.inf) -> None:
    try:
        ok = type(value) in (int, float) and math.isfinite(value) and lo <= value <= hi
    except OverflowError:
        ok = False
    _require(ok, where)


def _probabilities(value, candidates: dict, where: str, nullable: bool = False) -> None:
    _require(isinstance(value, dict) and value.keys() == candidates.keys(), where)
    for p in value.values():
        if p is not None or not nullable:
            _number(p, where, 0, 1)


def _observed(value: dict, candidates: dict, where: str) -> None:
    """Optional observed counts on a modeled race: both fields or neither.

    vote_share divides by every reported vote (pooled "other" included), so the
    displayed candidates' shares may sum to less than one, never more.
    """
    _require(("votes" in value) == ("vote_share" in value), where)
    if "votes" not in value:
        return
    votes, shares = value["votes"], value["vote_share"]
    _require(isinstance(votes, dict) and votes.keys() == candidates.keys(), where)
    _require(all(type(v) is int and v >= 0 for v in votes.values()), where)
    _probabilities(shares, candidates, where)
    _require(sum(shares.values()) <= 1 + 1e-3, where)
    if sum(votes.values()) == 0:
        _require(all(p == 0 for p in shares.values()), where)


def _state(value: dict, where: str, *, live: bool) -> None:
    base = {"state", "race", "race_type", "district", "as_of", "status", "modeled"}
    _require(isinstance(value, dict), where)
    _require(type(value.get("modeled")) is bool, where)
    if value.get("status") == "waiting":
        _shape(value, base, base, where)
    elif value["modeled"] is False:
        keys = base | {"candidates", "votes", "vote_share", "pct_reporting"}
        _shape(value, keys, keys, where)
        _require(value["status"] == "live", where)
        candidates, votes, shares = value["candidates"], value["votes"], value["vote_share"]
        _require(isinstance(candidates, dict) and bool(candidates)
                 and all(isinstance(k, str) and bool(k) and isinstance(v, str)
                         for k, v in candidates.items()), where)
        _require(isinstance(votes, dict) and votes.keys() == candidates.keys(), where)
        _require(all(type(v) is int and v >= 0 for v in votes.values()), where)
        total = sum(votes.values())
        _require(total > 0, where)
        _probabilities(shares, candidates, where)
        for candidate in candidates:
            _require(math.isclose(shares[candidate], votes[candidate] / total), where)
        if value["pct_reporting"] is not None:
            _number(value["pct_reporting"], where, 0, 1)
    else:
        common = base | {"candidates", "p_win"}
        if "rcv_status" in value:
            required = common | {"rcv_status", "p_outright", "p_via_rcv", "p_no_rcv_needed"}
            _shape(value, required | {"votes", "vote_share"}, required, where)
        else:
            required = common | {"margin", "reported_votes", "expected_votes", "share_counted"}
            _shape(value, required | {"counties", "votes", "vote_share"}, required, where)
        _require(value["status"] == "live", where)
        candidates = value["candidates"]
        _require(isinstance(candidates, dict) and bool(candidates) and all(isinstance(v, str) for v in candidates.values()), where)
        _probabilities(value["p_win"], candidates, where, nullable="rcv_status" in value)
        _observed(value, candidates, where)
        if "rcv_status" in value:
            status = value["rcv_status"]
            _require(status in {"awaiting_first_choices", "awaiting_rcv", "unresolved", "resolved"}, where)
            for key in ("p_outright", "p_via_rcv"):
                _probabilities(value[key], candidates, where, nullable=True)
            if value["p_no_rcv_needed"] is not None:
                _number(value["p_no_rcv_needed"], where, 0, 1)
            if status != "resolved":
                _require(all(p is None for p in value["p_win"].values()), where)
            else:
                for c in candidates:
                    a, b, p = value["p_outright"][c], value["p_via_rcv"][c], value["p_win"][c]
                    _require(a is not None and b is not None and p is not None and math.isclose(a + b, p), where)
        else:
            _shape(value["margin"], {"median", "p80", "p95"}, {"median", "p80", "p95"}, where)
            _number(value["margin"]["median"], where, -1, 1)
            for key in ("p80", "p95"):
                interval = value["margin"][key]
                _require(isinstance(interval, list) and len(interval) == 2, where)
                for n in interval:
                    _number(n, where, -1, 1)
                _require(interval[0] <= value["margin"]["median"] <= interval[1], where)
            for key in ("reported_votes", "expected_votes"):
                _require(type(value[key]) is int and value[key] >= 0, where)
            _require(not live or value["reported_votes"] > 0, where)
            _number(value["share_counted"], where, 0, 1)
            if "counties" in value:
                _require(isinstance(value["counties"], list), where)
                for county in value["counties"]:
                    fields = {"id", "status", "reported_votes", "reported_margin", "counted_share", "expected_margin"}
                    _shape(county, fields, fields, where)
                    _require(isinstance(county["id"], str) and county["status"] in {"none", "partial", "complete"}, where)
                    _require(type(county["reported_votes"]) is int and county["reported_votes"] >= 0, where)
                    for key in ("reported_margin", "expected_margin"):
                        if county[key] is not None:
                            _number(county[key], where, -1, 1)
                    _number(county["counted_share"], where, 0, 1)
    _require(all(isinstance(value[k], str) and bool(value[k]) for k in ("state", "race", "race_type")), where)
    _require(value["district"] is None or type(value["district"]) is int, where)
    _require(districts.race_identity(value["race"])
             == (value["state"], value["race_type"], value["district"]), where)
    _require(value["as_of"] is None or isinstance(value["as_of"], str), where)


_RACE_FILE = re.compile(r"(?:.*/)?races/([^/]+)\.json")


def _file_kind(relative: str) -> str:
    """summary, house, index or race; anything else isn't a public file."""
    name = relative.rsplit("/", 1)[-1]
    if name in ("summary.json", "house.json", "index.json"):
        return name.removesuffix(".json")
    match = _RACE_FILE.fullmatch(relative)
    _require(match is not None and districts.race_identity(match[1]) is not None, relative)
    return "race"


def _entries(value: dict, kind: str) -> list:
    if kind in ("summary", "house"):
        return value["states" if kind == "summary" else "races"]
    return [value] if kind == "race" else []


def _document(value, where: str, live: bool, kind: str) -> None:
    _require(isinstance(value, dict), where)
    if kind in ("summary", "house"):
        # summary.json holds Senate races, house.json House races; one entry per race.
        listed = "states" if kind == "summary" else "races"
        keys = {"generated_at", "mode", listed}
        _shape(value, keys, keys, where)
        _require(value["mode"] in {"live", "replay"} and isinstance(value["generated_at"], str), where)
        _require(isinstance(value[listed], list) and bool(value[listed]), where)
        for race in value[listed]:
            _state(race, where, live=live or value["mode"] == "live")
            _require((race["race_type"] == "house") == (kind == "house"), where)
        _require(len({race["race"] for race in value[listed]}) == len(value[listed]), where)
    elif kind == "index":
        keys = {"state", "pair", "order", "seed", "frames"}
        _shape(value, keys, keys, where)
        _require(value["state"] == "GA" and value["pair"] in {"primary", "secondary"}, where)
        _require(value["order"] in {"random", "timezone", "d_first", "r_first", "ed_first"} and type(value["seed"]) is int, where)
        _require(isinstance(value["frames"], list) and bool(value["frames"]), where)
        previous = -1.0
        for frame in value["frames"]:
            _shape(frame, {"time", "summary"}, {"time", "summary"}, where)
            _number(frame["time"], where, 0)
            _require(frame["time"] > previous and isinstance(frame["summary"], str)
                     and re.fullmatch(r"frames/\d{6}/summary\.json", frame["summary"]) is not None, where)
            previous = frame["time"]
    else:
        # races/{race_id}.json: one modeled race, named by its own ID.
        _state(value, where, live=live)
        _require(value["modeled"] is True and _RACE_FILE.fullmatch(where)[1] == value["race"], where)


class _UniquePrivateLoader(yaml.SafeLoader):
    pass


def _unique_private_mapping(loader, node):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str) or key in result:
            raise ValueError("invalid private mapping")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniquePrivateLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_private_mapping,
)


@dataclass(frozen=True, repr=False)
class _PrivatePriors:
    tokens: set  # every prior value and rounding: numbers outside race entries
    text: set  # the non-integer ones: numbers written inside any text
    precise: dict[str, set]  # per race, values with PRECISE_DECIMALS+: numbers in its entry
    own_text: dict[str, set]  # per race, its non-integer values: text in its entry

    @property
    def races(self) -> frozenset[str]:
        return frozenset(self.precise)


def _decimals(x: float) -> int:
    return max(0, -Decimal(repr(float(x))).normalize().as_tuple().exponent)


def _private_priors(path: Path) -> _PrivatePriors:
    # All failures are deliberately content-free: YAML diagnostics can quote lines.
    try:
        doc = yaml.load(path.read_text(), Loader=_UniquePrivateLoader)
        if not isinstance(doc, dict) or set(doc) != {"priors"} or not isinstance(doc["priors"], dict) or not doc["priors"]:
            raise ValueError
        tokens, text = set(), set()
        precise, own_text = {}, {}
        fields = {"margin", "margin_sd", "turnout_ratio", "turnout_sd"}
        for race, prior in doc["priors"].items():
            if prior is None:
                continue
            if not isinstance(prior, dict) or set(prior) != fields:
                raise ValueError
            exact, written = precise[race], own_text[race] = set(), set()
            for key, value in prior.items():
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError
                if (key == "margin" and not -1 <= value <= 1) or (key != "margin" and value <= 0):
                    raise ValueError
                for n in (value, round(value, 3), round(value, 4)):
                    tokens.update((n, str(n)))
                    if _decimals(n) > 0:
                        written.update((n, str(n)))
                    if _decimals(n) >= PRECISE_DECIMALS:
                        exact.update((n, str(n)))
            text |= written
        if not tokens:
            raise ValueError
        return _PrivatePriors(tokens, text, precise, own_text)
    except (OSError, ValueError, TypeError, OverflowError, yaml.YAMLError):
        raise PublicJSONError("private priors unavailable or invalid; contents withheld") from None


def _scan_values(value, tokens: set, where: str, text: set | None = None) -> None:
    """Numbers are compared with `tokens`; text (and numbers inside it) with `text`."""
    text = tokens if text is None else text
    if isinstance(value, dict):
        forbidden = {"marginsd", "turnoutratio", "turnoutsd", "baselinemargin", "baselinevotes",
                     "demographics", "covariates", "feedurl", "electionid", "config", "tauswing",
                     "tauturnout", "systematicswing", "systematicturnout"}
        for key, v in value.items():
            normalized = re.sub(r"[^a-z]", "", key.casefold())
            if "prior" in normalized or normalized in forbidden:
                raise PublicJSONError("private/config key in public output; path and key withheld")
            _scan_values(key, tokens, where, text)
            _scan_values(v, tokens, where, text)
    elif isinstance(value, list):
        for v in value:
            _scan_values(v, tokens, where, text)
    elif type(value) in (str, int, float):
        copied = value in (text if isinstance(value, str) else tokens)
        if isinstance(value, str):
            # Includes embedded, signed, decimal and scientific numeric literals.
            copied = copied or any(
                float(n) in text or float(n.lstrip("+-")) in text
                for n in re.findall(
                    r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?", value,
                )
            )
        if copied:
            raise PublicJSONError("possible private-value copy; path and value withheld")


def _scannable(entry: dict) -> dict:
    """A copy of a validated race entry without the fields that can't carry a prior."""
    entry = {k: v for k, v in entry.items() if k not in ("state", "race", "race_type", "district")}
    votes = entry.pop("votes", None)
    shares = entry.pop("vote_share", None)
    if votes is not None:
        total = sum(votes.values())
        # Shares are rounded to 4 places on modeled races and exact on results-only ones.
        kept = {k: p for k, p in shares.items()
                if not math.isclose(p, votes[k] / total if total else 0.0, abs_tol=5e-5)}
        if kept:
            entry["vote_share"] = kept
    entry.pop("reported_votes", None)
    if "counties" in entry:
        entry["counties"] = [{k: v for k, v in c.items() if k != "reported_votes"} for c in entry["counties"]]
    return entry


def _scan_document(value: dict, kind: str, private: _PrivatePriors | None, where: str) -> None:
    """Race entries against their own race's prior (module docstring); the rest against all."""
    if private is None:
        _scan_values(value, set(), where)  # key names only
        return
    for entry in _entries(value, kind):
        race = entry["race"]
        _scan_values(_scannable(entry), private.precise.get(race, set()), where,
                     private.own_text.get(race, set()))
    if kind in ("summary", "house"):
        rest = {k: v for k, v in value.items() if k not in ("states", "races")}
    else:
        rest = {} if kind == "race" else value
    _scan_values(rest, private.tokens, where, private.text)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("nonfinite JSON constant")


def _check_live_coverage(value: dict, kind: str, private: _PrivatePriors) -> None:
    for entry in _entries(value, kind):
        if entry["modeled"] is not False and entry["race"] not in private.races:
            raise PublicJSONError("live modeled race has no configured private prior")


def check_tree(root: Path, *, priors: Path | None = None, mode: str | None = None) -> ScanReport:
    if mode not in (None, "live", "replay"):
        raise PublicJSONError("invalid publication mode")
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise PublicJSONError("public output directory is missing or unsafe")
    private = _private_priors(Path(priors)) if priors is not None else None
    tokens = private.tokens if private is not None else None
    count = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink() or "config" in {p.casefold() for p in relative.parts} or path.suffix.lower() in {".yaml", ".yml"} or path.name.startswith(".env"):
            raise PublicJSONError("private/config artifact or symlink in public output")
        where = relative.as_posix()
        # A race file's name is its race ID, which the file's own entry must match.
        named = _RACE_FILE.fullmatch(where)
        _scan_values(where.replace(named[1], "") if named else where, set(),
                     where, private.text if private is not None else set())
        if path.is_dir():
            continue
        if not path.is_file() or path.suffix.lower() != ".json":
            raise PublicJSONError("unexpected non-JSON artifact in public data output; path withheld")
        try:
            value = json.loads(path.read_text(), object_pairs_hook=_pairs, parse_constant=_constant)
        except (OSError, UnicodeError, ValueError):
            raise PublicJSONError("invalid JSON; path and contents withheld") from None
        live = (mode == "live" or "live" in {p.casefold() for p in root.parts}
                or "live" in {p.casefold() for p in relative.parts}
                or (isinstance(value, dict) and value.get("mode") == "live"))
        if live and tokens is None:
            raise PublicJSONError("live output requires private priors for value checks")
        try:
            kind = _file_kind(where)
            _document(value, where, live, kind)
            _scan_document(value, kind, private, where)
            if live:
                _check_live_coverage(value, kind, private)
        except (TypeError, KeyError, AttributeError, OverflowError, RecursionError):
            raise PublicJSONError("invalid public payload; path and contents withheld") from None
        count += 1
    if not count:
        raise PublicJSONError("no public JSON files found")
    return ScanReport(count, tokens is not None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--priors", type=Path, help="private prior file; values are never printed")
    coverage = parser.add_mutually_exclusive_group()
    coverage.add_argument("--require-priors", action="store_true", help="require private coverage (the default)")
    coverage.add_argument("--structure-only", action="store_true", help="replay shapes only; never a privacy pass")
    parser.add_argument("--mode", choices=("live", "replay"), help="force live checks for flat export directories")
    args = parser.parse_args(argv)
    if args.structure_only and args.priors is not None:
        parser.error("--structure-only cannot be combined with --priors")
    private = None if args.structure_only else (args.priors or CONFIG / "priors.yaml")
    try:
        report = check_tree(args.root, priors=private, mode=args.mode)
    except PublicJSONError as exc:
        print(f"FAIL: {exc}")
        return 1
    if report.private_values_checked:
        print(f"PASS: {report.files} JSON files; private-input copy checks complete; posterior independence not tested")
    else:
        print(f"STRUCTURE ONLY: {report.files} JSON files; private-value coverage unavailable; no privacy pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
