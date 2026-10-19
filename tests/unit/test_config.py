"""Config mistakes must fail before a poll cycle; private values stay out of errors."""

import copy
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

from torehancast import config

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def config_dir(tmp_path):
    for name in ("races.yaml", "feeds.yaml", "priors.example.yaml"):
        shutil.copy(ROOT / "config" / name, tmp_path / name)
    return tmp_path


def edit(directory, name, change):
    path = directory / name
    document = yaml.safe_load(path.read_text())
    change(document)
    path.write_text(yaml.safe_dump(document))


def cli(directory):
    return subprocess.run(
        [sys.executable, "-m", "torehancast.config", "validate", "--config-dir", str(directory)],
        capture_output=True, text=True,
    )


def test_registry_loads_every_planned_race_and_baseline_exception():
    loaded = config.load_config(ROOT / "config")
    assert {race.state for race in loaded.races.values()} == {
        "GA", "NC", "FL", "TX", "OH", "IA", "KS", "SC", "MI", "MN", "ME", "AK", "NE",
    }
    assert len(loaded.races) == 13
    assert loaded.races["2026-GA-SEN"].baseline == "2022_sen"
    assert loaded.races["2026-ME-SEN"].baseline == "2020_sen"
    assert loaded.races["2026-MN-SEN"].baseline == "2024_pres"
    assert loaded.races["2026-AK-SEN"].baseline == "2026_prim_sen"
    assert loaded.races["2026-AK-SEN"].fallback_baseline == "2024_gen_house"
    assert loaded.races["2026-AK-SEN"].unit == "house-district"
    assert loaded.races["2026-ME-SEN"].ranked_choice
    assert loaded.races["2026-AK-SEN"].ranked_choice
    assert loaded.races["2026-NE-SEN"].baseline == "2024_sen"
    assert set(loaded.feeds) == set(loaded.races) == set(loaded.priors)


def test_fresh_checkout_validates_with_unset_priors(config_dir):
    result = cli(config_dir)
    assert result.returncode == 0, result.stderr
    assert "13 races" in result.stdout
    assert "13 priors unset" in result.stdout
    assert not (config_dir / "priors.yaml").exists()


def test_private_prior_is_loaded_without_printing_values(config_dir):
    document = yaml.safe_load((config_dir / "priors.example.yaml").read_text())
    document["priors"]["2026-GA-SEN"] = {
        "margin": 0.123456789, "margin_sd": 0.06, "turnout_ratio": 1.2, "turnout_sd": 0.1,
    }
    (config_dir / "priors.yaml").write_text(yaml.safe_dump(document))
    loaded = config.load_config(config_dir)
    assert loaded.priors["2026-GA-SEN"].margin == 0.123456789
    assert "0.123456789" not in repr(loaded)
    result = cli(config_dir)
    assert result.returncode == 0
    assert "12 priors unset" in result.stdout
    assert "0.123456789" not in result.stdout + result.stderr


def test_example_values_never_replace_missing_private_priors(config_dir):
    edit(config_dir, "priors.example.yaml", lambda doc: doc["priors"].update({
        "2026-GA-SEN": {"margin": 0.123456789, "margin_sd": 0.06, "turnout_ratio": 1.2, "turnout_sd": 0.1},
    }))
    assert config.load_config(config_dir).priors["2026-GA-SEN"] is None


def test_broken_private_file_symlink_fails_instead_of_using_template(config_dir):
    (config_dir / "priors.yaml").symlink_to(config_dir / "missing-private-file.yaml")
    result = cli(config_dir)
    assert result.returncode == 1
    assert "cannot read" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("filename, section", [("feeds.yaml", "feeds"), ("priors.example.yaml", "priors")])
@pytest.mark.parametrize("operation", ["missing", "unknown"])
def test_cross_file_race_mismatches_fail(config_dir, filename, section, operation):
    def change(doc):
        if operation == "missing":
            doc[section].pop("2026-GA-SEN")
        else:
            doc[section]["2026-ZZ-SEN"] = copy.deepcopy(doc[section]["2026-GA-SEN"])
    edit(config_dir, filename, change)
    with pytest.raises(config.ConfigError, match="race IDs"):
        config.load_config(config_dir)


@pytest.mark.parametrize("field, value", [
    ("state", "ZZ"), ("race_type", "senat"), ("unit", "precint"),
    ("ranked_choice", "false"), ("priority", True), ("priority", 0),
    ("baseline", ""), ("status", "almost"), ("typo", "ignored?"),
])
def test_invalid_registry_fields_fail(config_dir, field, value):
    edit(config_dir, "races.yaml", lambda doc: doc["races"]["2026-GA-SEN"].update({field: value}))
    with pytest.raises(config.ConfigError):
        config.load_config(config_dir)


@pytest.mark.parametrize("field, value", [
    ("url", "http://results.sos.ga.gov/data"), ("url", "https://user:secret@example.org/data"),
    ("status", "almost"), ("election_id", 2026), ("params", {"date": [2026]}),
    ("adapter", "bad adapter"), ("typo", "ignored?"),
])
def test_invalid_feed_fields_fail(config_dir, field, value):
    edit(config_dir, "feeds.yaml", lambda doc: doc["feeds"]["2026-GA-SEN"].update({field: value}))
    with pytest.raises(config.ConfigError):
        config.load_config(config_dir)


def test_ready_feed_needs_url_adapter_and_election_id(config_dir):
    edit(config_dir, "feeds.yaml", lambda doc: doc["feeds"]["2026-GA-SEN"].update(status="ready", election_id=None))
    with pytest.raises(config.ConfigError, match="ready"):
        config.load_config(config_dir)


def test_feed_settings_can_be_swapped_without_changing_code(config_dir):
    edit(config_dir, "feeds.yaml", lambda doc: doc["feeds"]["2026-GA-SEN"].update(
        status="ready", url="https://results.sos.ga.gov/replacement", election_id="replacement",
    ))
    loaded = config.load_config(config_dir)
    assert loaded.feeds["2026-GA-SEN"].url == "https://results.sos.ga.gov/replacement"
    assert loaded.feeds["2026-GA-SEN"].election_id == "replacement"


@pytest.mark.parametrize("field, value", [
    ("margin", 1.01), ("margin", -1.01), ("margin", float("nan")), ("margin", 10**400),
    ("margin_sd", 0), ("margin_sd", True), ("turnout_ratio", -1),
    ("turnout_sd", float("inf")), ("margin", "PRIVATE_SENTINEL"),
    ("extra", 0.5),
])
def test_invalid_private_priors_fail_without_exposing_values(config_dir, field, value):
    document = yaml.safe_load((config_dir / "priors.example.yaml").read_text())
    prior = {"margin": 0.123456789, "margin_sd": 0.06, "turnout_ratio": 1.2, "turnout_sd": 0.1}
    prior[field] = value
    document["priors"]["2026-GA-SEN"] = prior
    (config_dir / "priors.yaml").write_text(yaml.safe_dump(document))
    result = cli(config_dir)
    assert result.returncode == 1
    assert "invalid config" in result.stderr
    assert "PRIVATE_SENTINEL" not in result.stderr + result.stdout
    assert "0.123456789" not in result.stderr + result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("contents", ["priors: [PRIVATE_SENTINEL", "priors:\n  secret: PRIVATE_SENTINEL\npriors: {}\n", "[]", ""])
def test_malformed_private_yaml_is_rejected_without_echoing_it(config_dir, contents):
    (config_dir / "priors.yaml").write_text(contents)
    result = cli(config_dir)
    assert result.returncode == 1
    assert "PRIVATE_SENTINEL" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_missing_required_file_fails_cleanly(config_dir):
    (config_dir / "feeds.yaml").unlink()
    result = cli(config_dir)
    assert result.returncode == 1
    assert "feeds.yaml" in result.stderr
    assert "Traceback" not in result.stderr


def test_duplicate_yaml_keys_do_not_silently_replace_a_race(config_dir):
    path = config_dir / "races.yaml"
    path.write_text(path.read_text() + "\nraces: {}\n")
    with pytest.raises(config.ConfigError, match="duplicate"):
        config.load_config(config_dir)


def test_every_named_adapter_is_a_real_module():
    # The validator only checks the name's shape; a typo like "ia_clarty" must fail here.
    adapters = {p.stem for p in (ROOT / "src" / "torehancast" / "adapters").glob("*.py")} - {"__init__"}
    loaded = config.load_config(ROOT / "config")
    named = {feed.adapter for feed in loaded.feeds.values() if feed.adapter is not None}
    assert named <= adapters, f"unknown adapters: {sorted(named - adapters)}"


def test_done_races_name_baselines_that_exist_in_elections_yaml():
    elections = yaml.safe_load((ROOT / "config" / "elections.yaml").read_text())
    loaded = config.load_config(ROOT / "config")
    for race_id, race in loaded.races.items():
        if race.status != "done":
            continue
        keys = set(elections.get(race.state, {}))
        assert race.baseline in keys, f"{race_id}: baseline {race.baseline!r} not in elections.yaml"
        if race.fallback_baseline is not None:
            assert race.fallback_baseline in keys, f"{race_id}: fallback {race.fallback_baseline!r} missing"
