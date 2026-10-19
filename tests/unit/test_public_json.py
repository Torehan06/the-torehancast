"""Public artifact checks reject accidental private/config payloads."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from torehancast import public_json

PAYLOAD = {
    "state": "GA", "race": "2022_sen", "as_of": "T+1.00h", "status": "live",
    "candidates": {"D": "Dem", "R": "Rep"}, "p_win": {"D": 0.6, "R": 0.4},
    "margin": {"median": 0.02, "p80": [-0.03, 0.04], "p95": [-0.05, 0.07]},
    "reported_votes": 1200, "expected_votes": 2000, "share_counted": 0.6,
}


def write(root, payload=PAYLOAD, mode="replay"):
    path = root / f"data/{mode}/GA.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def private(path):
    path.write_text("priors:\n  2026-GA-SEN:\n    margin: 0.0234567\n    margin_sd: 0.0678912\n    turnout_ratio: 1.23456789\n    turnout_sd: 0.143258\n")
    return path


def test_replay_reports_missing_private_value_coverage(tmp_path):
    write(tmp_path)
    report = public_json.check_tree(tmp_path)
    assert report.files == 1
    assert report.private_values_checked is False


def test_private_value_scan_succeeds_with_unrelated_public_values(tmp_path):
    write(tmp_path / "out")
    report = public_json.check_tree(tmp_path / "out", priors=private(tmp_path / "priors.yaml"))
    assert report.files == 1 and report.private_values_checked


@pytest.mark.parametrize("key", ["prior", "margin_sd", "baseline_margin", "demographics", "feed_url"])
def test_private_or_unknown_fields_are_rejected_at_any_depth(tmp_path, key):
    payload = {"generated_at": "now", "mode": "replay", "states": [{**PAYLOAD, key: 0.0234567}]}
    write(tmp_path, payload)
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path)


@pytest.mark.parametrize("value", [0.0234567, 0.0235, "0.0234567"])
def test_exact_and_rounded_private_values_are_rejected_without_echoing_secrets(tmp_path, value):
    priors = private(tmp_path / "priors.yaml")
    payload = copy.deepcopy(PAYLOAD)
    if isinstance(value, str):
        payload["candidates"]["D"] = value
    else:
        payload["margin"]["median"] = value
    write(tmp_path / "out", payload)
    with pytest.raises(public_json.PublicJSONError) as caught:
        public_json.check_tree(tmp_path / "out", priors=priors)
    assert "0.023" not in str(caught.value)


def test_live_scan_requires_private_config_coverage(tmp_path):
    write(tmp_path, mode="live")
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path)


def test_waiting_state_cannot_contain_prior_derived_projections(tmp_path):
    payload = {**PAYLOAD, "status": "waiting"}
    write(tmp_path, payload)
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path)


@pytest.mark.parametrize("text", ["{", '{"state":"GA","state":"AK"}', '{"x":NaN}', '[]'])
def test_invalid_or_ambiguous_json_fails(tmp_path, text):
    path = write(tmp_path)
    path.write_text(text)
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path)


def test_empty_tree_does_not_pass_vacuously(tmp_path):
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path)


def test_copied_config_file_is_rejected_even_if_not_json(tmp_path):
    write(tmp_path)
    (tmp_path / "priors.yaml").write_text("private material")
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path)


def test_symlink_to_private_material_is_rejected(tmp_path):
    write(tmp_path / "out")
    (tmp_path / "out/link.json").symlink_to(private(tmp_path / "priors.yaml"))
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path / "out")


@pytest.mark.parametrize("missing", [True, False])
def test_explicit_private_config_errors_do_not_print_contents(tmp_path, missing):
    write(tmp_path / "out")
    priors = tmp_path / "priors.yaml"
    if not missing:
        priors.write_text("priors: [PRIVATE_CANARY: }\n")
    with pytest.raises(public_json.PublicJSONError) as caught:
        public_json.check_tree(tmp_path / "out", priors=priors)
    assert "PRIVATE_CANARY" not in str(caught.value)


def test_checker_script_is_runnable_and_reports_partial_coverage(tmp_path):
    write(tmp_path / "out")
    script = Path(__file__).parents[2] / "scripts/check_public_json.py"
    result = subprocess.run([sys.executable, str(script), str(tmp_path / "out")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "unavailable" in result.stdout.lower()
    strict = subprocess.run([sys.executable, str(script), str(tmp_path / "out"), "--require-priors"], capture_output=True, text=True)
    assert strict.returncode != 0


def test_private_identifiers_cannot_hide_in_candidate_dictionary_keys(tmp_path):
    payload = copy.deepcopy(PAYLOAD)
    payload["candidates"]["prior"] = payload["candidates"].pop("D")
    payload["p_win"]["prior"] = payload["p_win"].pop("D")
    write(tmp_path, payload)
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path)


def test_private_value_cannot_hide_in_a_dictionary_key(tmp_path):
    payload = copy.deepcopy(PAYLOAD)
    payload["candidates"]["0.0234567"] = payload["candidates"].pop("D")
    payload["p_win"]["0.0234567"] = payload["p_win"].pop("D")
    write(tmp_path / "out", payload)
    with pytest.raises(public_json.PublicJSONError) as caught:
        public_json.check_tree(tmp_path / "out", priors=private(tmp_path / "priors.yaml"))
    assert "0.023" not in str(caught.value)


def test_empty_private_document_is_not_checked_live_coverage(tmp_path):
    write(tmp_path / "out", mode="live")
    priors = tmp_path / "priors.yaml"
    priors.write_text("priors: {}\n")
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path / "out", priors=priors)
