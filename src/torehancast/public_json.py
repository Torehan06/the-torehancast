"""Check public artifact shapes and accidental copies of private config values.

This verifies public artifact shapes and private-input copies, not posterior independence.
Historical replay priors are intentionally public; live private priors are not.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .elections import CONFIG


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
    base = {"state", "race", "as_of", "status", "modeled"}
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
    _require(all(isinstance(value[k], str) and bool(value[k]) for k in ("state", "race")), where)
    _require(value["as_of"] is None or isinstance(value["as_of"], str), where)


def _document(value, where: str, live: bool) -> None:
    _require(isinstance(value, dict), where)
    if "states" in value:
        keys = {"generated_at", "mode", "states"}
        _shape(value, keys, keys, where)
        _require(value["mode"] in {"live", "replay"} and isinstance(value["generated_at"], str), where)
        _require(isinstance(value["states"], list) and bool(value["states"]), where)
        for state in value["states"]:
            _state(state, where, live=live or value["mode"] == "live")
    elif "frames" in value:
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
        _state(value, where, live=live)


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
    tokens: set
    races: frozenset[str]


def _private_priors(path: Path) -> _PrivatePriors:
    # All failures are deliberately content-free: YAML diagnostics can quote lines.
    try:
        doc = yaml.load(path.read_text(), Loader=_UniquePrivateLoader)
        if not isinstance(doc, dict) or set(doc) != {"priors"} or not isinstance(doc["priors"], dict) or not doc["priors"]:
            raise ValueError
        tokens = set()
        races = set()
        fields = {"margin", "margin_sd", "turnout_ratio", "turnout_sd"}
        for race, prior in doc["priors"].items():
            if prior is None:
                continue
            if not isinstance(prior, dict) or set(prior) != fields:
                raise ValueError
            races.add(race)
            for key, value in prior.items():
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError
                if (key == "margin" and not -1 <= value <= 1) or (key != "margin" and value <= 0):
                    raise ValueError
                for n in (value, round(value, 3), round(value, 4)):
                    tokens.add(n)
                    tokens.add(str(n))
        if not tokens:
            raise ValueError
        return _PrivatePriors(tokens, frozenset(races))
    except (OSError, ValueError, TypeError, OverflowError, yaml.YAMLError):
        raise PublicJSONError("private priors unavailable or invalid; contents withheld") from None


def _scan_values(value, tokens: set, where: str) -> None:
    if isinstance(value, dict):
        forbidden = {"marginsd", "turnoutratio", "turnoutsd", "baselinemargin", "baselinevotes",
                     "demographics", "covariates", "feedurl", "electionid", "config", "tauswing",
                     "tauturnout", "systematicswing", "systematicturnout"}
        for key, v in value.items():
            normalized = re.sub(r"[^a-z]", "", key.casefold())
            if "prior" in normalized or normalized in forbidden:
                raise PublicJSONError("private/config key in public output; path and key withheld")
            _scan_values(key, tokens, where)
            _scan_values(v, tokens, where)
    elif isinstance(value, list):
        for v in value:
            _scan_values(v, tokens, where)
    elif type(value) in (str, int, float):
        copied = value in tokens
        if isinstance(value, str):
            # Includes embedded, signed, decimal and scientific numeric literals.
            copied = copied or any(
                float(n) in tokens or float(n.lstrip("+-")) in tokens
                for n in re.findall(
                    r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?", value,
                )
            )
        if copied:
            raise PublicJSONError("possible private-value copy; path and value withheld")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("nonfinite JSON constant")


def _check_live_coverage(value: dict, private: _PrivatePriors) -> None:
    states = value["states"] if "states" in value else [value]
    for state in states:
        if state["modeled"] is False:
            continue
        race = state["race"]
        if re.match(r"^[0-9]{4}-[A-Z]{2}-", race):
            covered = race in private.races and race.split("-")[1] == state["state"]
        else:
            # Legacy display labels identify a race only if this state has one
            # configured prior. Canonical IDs must always match exactly.
            covered = sum(k.split("-")[1:2] == [state["state"]]
                          for k in private.races) == 1
        if not covered:
            raise PublicJSONError("live modeled race has no unambiguous configured private prior")


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
        where = str(relative)
        _scan_values(where, tokens if tokens is not None else set(), where)
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
            _scan_values(value, tokens if tokens is not None else set(), where)
            _document(value, where, live)
            if live:
                _check_live_coverage(value, private)
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
