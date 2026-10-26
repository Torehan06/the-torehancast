"""Privacy regressions: fail closed and never echo secret-bearing content."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from torehancast import public_json
from test_public_json import PAYLOAD, private, write


@pytest.mark.parametrize("text", [
    "priors: {2026-GA-SEN: null}\n",
    "priors:\n  2026-GA-SEN: null\n  2026-GA-SEN: null\n",
])
def test_unset_or_duplicate_private_priors_are_not_checked_coverage(tmp_path, text):
    write(tmp_path / "out", mode="live")
    path = tmp_path / "priors.yaml"
    path.write_text(text)
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path / "out", priors=path)


def test_duplicate_prior_field_cannot_hide_a_value_from_the_scan(tmp_path):
    path = private(tmp_path / "priors.yaml")
    path.write_text(path.read_text().replace("margin: 0.0234567", "margin: 0.9\n    margin: 0.0234567"))
    write(tmp_path / "out", mode="live")
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path / "out", priors=path)


@pytest.mark.parametrize("text", [
    "private value = 0.0234567", "private value = 2.34567e-2",
    "rounded value (0.0235)", "candidate0.0234567suffix",
])
def test_private_numeric_tokens_inside_strings_are_rejected(tmp_path, text):
    payload = copy.deepcopy(PAYLOAD)
    payload["candidates"]["D"] = text
    write(tmp_path / "out", payload)
    with pytest.raises(public_json.PublicJSONError) as exc:
        public_json.check_tree(tmp_path / "out", priors=private(tmp_path / "priors.yaml"))
    assert "0.023" not in str(exc.value)


@pytest.mark.parametrize("name", ["leak.txt", "leak.html", "leak.js", "priors", ".DS_Store"])
def test_unscanned_public_files_are_rejected(tmp_path, name):
    write(tmp_path / "out")
    (tmp_path / "out" / name).write_text("private value = 0.0234567")
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path / "out", priors=private(tmp_path / "priors.yaml"))


def test_a_live_directory_root_still_requires_private_coverage(tmp_path):
    path = write(tmp_path, mode="live")
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(path.parent)


def test_explicit_live_mode_checks_even_a_flat_directory(tmp_path):
    (tmp_path / "races").mkdir()
    (tmp_path / "races/2026-GA-SEN.json").write_text(json.dumps(PAYLOAD))
    with pytest.raises(public_json.PublicJSONError, match="requires private priors"):
        public_json.check_tree(tmp_path, mode="live")


def test_live_race_must_have_its_own_nonnull_private_prior(tmp_path):
    payload = {**PAYLOAD, "state": "NC", "race": "2026-NC-SEN"}
    write(tmp_path / "out", payload, mode="live")
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path / "out", priors=private(tmp_path / "priors.yaml"))


def test_private_value_in_a_filename_is_rejected_without_echo(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "0.0234567.json").write_text(json.dumps(PAYLOAD))
    with pytest.raises(public_json.PublicJSONError) as exc:
        public_json.check_tree(out, priors=private(tmp_path / "priors.yaml"))
    assert "0.023" not in str(exc.value)


def test_malformed_payload_diagnostics_never_echo_a_secret_filename(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    (out / "PRIVATE_CANARY.json").write_text("{")
    assert public_json.main([str(out)]) == 1
    assert "PRIVATE_CANARY" not in capsys.readouterr().out


def test_private_prior_file_is_gitignored():
    root = Path(__file__).parents[2]
    result = subprocess.run(["git", "check-ignore", "config/priors.yaml"], cwd=root,
                            capture_output=True, text=True)
    assert result.returncode == 0


def test_cli_default_never_calls_missing_private_coverage_a_pass(tmp_path, monkeypatch, capsys):
    write(tmp_path / "out")
    monkeypatch.setattr(public_json, "CONFIG", tmp_path / "missing-config")
    assert public_json.main([str(tmp_path / "out")]) == 1
    assert "PASS" not in capsys.readouterr().out


def test_cli_requires_explicit_opt_in_for_structure_only(tmp_path, capsys):
    write(tmp_path)
    assert public_json.main([str(tmp_path), "--structure-only"]) == 0
    output = capsys.readouterr().out
    assert "STRUCTURE ONLY" in output and "PASS" not in output


def test_exact_race_identifier_cannot_use_another_prior_in_the_same_state(tmp_path):
    payload = {**PAYLOAD, "race": "2026-GA-SEN-SPECIAL"}
    write(tmp_path / "out", payload, mode="live")
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path / "out", priors=private(tmp_path / "priors.yaml"))


def test_nested_live_directory_root_does_not_lose_live_mode(tmp_path):
    path = write(tmp_path, mode="live/nested")
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(path.parent)


def test_malformed_field_types_fail_with_redacted_cli_diagnostics(tmp_path, capsys):
    payload = copy.deepcopy(PAYLOAD)
    payload["counties"] = [{"id": "A", "status": ["PRIVATE_CANARY"],
                            "reported_votes": 1, "reported_margin": 0,
                            "counted_share": 0.5, "expected_margin": 0}]
    write(tmp_path / "out", payload)
    assert public_json.main([str(tmp_path / "out"), "--priors", str(private(tmp_path / "priors.yaml"))]) == 1
    assert "PRIVATE_CANARY" not in capsys.readouterr().out


def test_live_canonical_race_must_match_payload_state(tmp_path):
    payload = {**PAYLOAD, "state": "NC", "race": "2026-GA-SEN"}
    write(tmp_path / "out", payload, mode="live")
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(tmp_path / "out", priors=private(tmp_path / "priors.yaml"))


@pytest.mark.parametrize("location", ["as_of", "filename", "directory"])
def test_private_positive_value_after_a_hyphen_is_not_hidden_by_a_sign(tmp_path, location):
    out = tmp_path / "out"
    out.mkdir()
    payload = copy.deepcopy(PAYLOAD)
    (out / "races").mkdir()
    name = "races/2026-GA-SEN.json"
    if location == "as_of":
        payload["as_of"] = "private-0.0234567"
    elif location == "filename":
        name = "snapshot-0.0234567.json"
    else:
        (out / "snapshot-0.0234567").mkdir()
    (out / name).write_text(json.dumps(payload))
    with pytest.raises(public_json.PublicJSONError):
        public_json.check_tree(out, priors=private(tmp_path / "priors.yaml"))
