"""Check public artifact shapes and accidental copies of private config values.

This is a conservative artifact check, not a proof of posterior independence.
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
        raise PublicJSONError(f"invalid public payload at {where}")


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


def _state(value: dict, where: str, *, live: bool) -> None:
    base = {"state", "race", "as_of", "status"}
    _require(isinstance(value, dict), where)
    if value.get("status") == "waiting":
        _shape(value, base, base, where)
    else:
        common = base | {"candidates", "p_win"}
        if "rcv_status" in value:
            keys = common | {"rcv_status", "p_outright", "p_via_rcv", "p_no_rcv_needed"}
            _shape(value, keys, keys, where)
        else:
            keys = common | {"margin", "reported_votes", "expected_votes", "share_counted", "counties"}
            _shape(value, keys, keys - {"counties"}, where)
        _require(value["status"] == "live", where)
        candidates = value["candidates"]
        _require(isinstance(candidates, dict) and bool(candidates) and all(isinstance(v, str) for v in candidates.values()), where)
        _probabilities(value["p_win"], candidates, where, nullable="rcv_status" in value)
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


def _private_tokens(path: Path) -> set:
    # All failures are deliberately content-free: YAML diagnostics can quote lines.
    try:
        doc = yaml.safe_load(path.read_text())
        if not isinstance(doc, dict) or set(doc) != {"priors"} or not isinstance(doc["priors"], dict):
            raise ValueError
        tokens = set()
        fields = {"margin", "margin_sd", "turnout_ratio", "turnout_sd"}
        for prior in doc["priors"].values():
            if prior is None:
                continue
            if not isinstance(prior, dict) or set(prior) != fields:
                raise ValueError
            for key, value in prior.items():
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError
                if (key == "margin" and not -1 <= value <= 1) or (key != "margin" and value <= 0):
                    raise ValueError
                for n in (value, round(value, 3), round(value, 4)):
                    tokens.add(n)
                    tokens.add(str(n))
        return tokens
    except (OSError, ValueError, TypeError, OverflowError, yaml.YAMLError):
        raise PublicJSONError("private priors unavailable or invalid; contents withheld") from None


def _scan_values(value, tokens: set, where: str) -> None:
    if isinstance(value, dict):
        for v in value.values():
            _scan_values(v, tokens, where)
    elif isinstance(value, list):
        for v in value:
            _scan_values(v, tokens, where)
    elif type(value) in (str, int, float) and value in tokens:
        raise PublicJSONError(f"possible private-value copy in {where}; value withheld")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("nonfinite JSON constant")


def check_tree(root: Path, *, priors: Path | None = None) -> ScanReport:
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise PublicJSONError("public output directory is missing or unsafe")
    tokens = _private_tokens(Path(priors)) if priors is not None else None
    count = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink() or "config" in relative.parts or path.suffix.lower() in {".yaml", ".yml"} or path.name.startswith(".env"):
            raise PublicJSONError("private/config artifact or symlink in public output")
        if not path.is_file() or path.suffix.lower() != ".json":
            continue
        where = str(relative)
        try:
            value = json.loads(path.read_text(), object_pairs_hook=_pairs, parse_constant=_constant)
        except (OSError, UnicodeError, ValueError):
            raise PublicJSONError(f"invalid JSON in {where}; contents withheld") from None
        live = "live" in relative.parts or (isinstance(value, dict) and value.get("mode") == "live")
        if live and tokens is None:
            raise PublicJSONError("live output requires private priors for value checks")
        _document(value, where, live)
        if tokens is not None:
            _scan_values(value, tokens, where)
        count += 1
    if not count:
        raise PublicJSONError("no public JSON files found")
    return ScanReport(count, tokens is not None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--priors", type=Path, help="private prior file; values are never printed")
    parser.add_argument("--require-priors", action="store_true")
    args = parser.parse_args(argv)
    private = args.priors
    if private is None and ((CONFIG / "priors.yaml").exists() or args.require_priors):
        private = CONFIG / "priors.yaml"
    try:
        report = check_tree(args.root, priors=private)
    except PublicJSONError as exc:
        print(f"FAIL: {exc}")
        return 1
    coverage = "checked" if report.private_values_checked else "unavailable (private file not supplied); replay structure only"
    print(f"PASS: {report.files} JSON files; private-value coverage: {coverage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
