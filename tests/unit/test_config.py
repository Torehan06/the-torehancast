"""Config mistakes must fail before a poll cycle; private values stay out of errors."""

import copy
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

from torehancast import config, districts, elections

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
    senate = {k: r for k, r in loaded.races.items() if r.race_type != "house"}
    assert {race.state for race in senate.values()} == {
        "GA", "NC", "FL", "TX", "OH", "IA", "KS", "SC", "MI", "MN", "ME", "AK", "NE",
    }
    assert len(senate) == 13
    assert len(loaded.races) == 13 + 63
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
    assert "76 races" in result.stdout
    assert "76 priors unset" in result.stdout
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
    assert "75 priors unset" in result.stdout
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
        contest="US Senate", candidates={"Jon Ossoff": "D", "Mike Collins": "R"},
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
    loaded = config.load_config(ROOT / "config")
    for race_id, race in loaded.races.items():
        if race.status != "done":
            continue
        keys = set(elections.specs(race.state))
        assert race.baseline in keys, f"{race_id}: baseline {race.baseline!r} not in elections.yaml"
        if race.fallback_baseline is not None:
            assert race.fallback_baseline in keys, f"{race_id}: fallback {race.fallback_baseline!r} missing"


def _ready(document, **changes):
    document["feeds"]["2026-NC-SEN"].update(status="ready", **changes)


@pytest.mark.parametrize("change", [
    lambda d: _ready(d, contest=None),
    lambda d: _ready(d, polls_close=None),
    lambda d: _ready(d, polls_close="2026-11-03T19:30:00"),  # no UTC offset
    lambda d: _ready(d, display={"D": "Roy Cooper"}),
    lambda d: _ready(d, candidates={"Roy Cooper": "D", "Michael Whatley": "other"}),
    lambda d: _ready(d, display={"D": "Roy Cooper", "R": "Michael Whatley", "G": "Michael Dublin"}),
])
def test_ready_feed_needs_contest_candidates_display_and_close(config_dir, change):
    edit(config_dir, "feeds.yaml", change)
    with pytest.raises(config.ConfigError):
        config.load_config(config_dir)


def test_ready_feed_needs_race_tau_pair(config_dir):
    edit(config_dir, "feeds.yaml", _ready)
    config.load_config(config_dir)
    edit(config_dir, "races.yaml", lambda d: d["races"]["2026-NC-SEN"].pop("tau_pair"))
    with pytest.raises(config.ConfigError):
        config.load_config(config_dir)


def test_live_fields_load():
    loaded = config.load_config(ROOT / "config")
    nc = loaded.feeds["2026-NC-SEN"]
    assert nc.candidates["Roy Cooper"] == "D" and nc.display["R"] == "Michael Whatley"
    assert nc.polls_close_at.isoformat() == "2026-11-03T19:30:00-05:00"
    assert loaded.races["2026-AK-SEN"].tau_pair == ("2024_prim_house", "2024_gen_house")
    for race in loaded.races.values():
        if race.tau_pair:
            for key in race.tau_pair + (race.baseline,):
                assert elections.baseline_path(race.state, key).exists(), (race.state, key)


def test_house_race_ids_must_name_a_real_district(config_dir):
    def rename(doc, old, new):
        doc["races"][new] = doc["races"].pop(old)
    for name in ("races.yaml", "feeds.yaml", "priors.example.yaml"):
        section = name.split(".")[0]
        edit(config_dir, name, lambda d, s=section: d[s].__setitem__("2026-NC-H15", d[s].pop("2026-NC-H01")))
    with pytest.raises(config.ConfigError, match="real district"):
        config.load_config(config_dir)


def test_a_senate_race_cannot_borrow_a_house_id(config_dir):
    edit(config_dir, "races.yaml", lambda d: d["races"]["2026-NC-H01"].update(race_type="senate"))
    with pytest.raises(config.ConfigError, match="real district"):
        config.load_config(config_dir)


def test_ranked_choice_house_races_match_state_law():
    loaded = config.load_config(ROOT / "config")
    house = {k: r for k, r in loaded.races.items() if r.race_type == "house"}
    assert {k for k, r in house.items() if r.ranked_choice} == {"2026-AK-HAL", "2026-ME-H02"}


# Results-only registry (config/results/<ST>.yaml)

@pytest.fixture
def results_dir(config_dir):
    shutil.copytree(ROOT / "config" / "results", config_dir / "results")
    return config_dir


def results(directory):
    return config.load_results(config.load_config(directory), directory)


def edit_results(directory, state, change):
    path = directory / "results" / f"{state}.yaml"
    document = yaml.safe_load(path.read_text())
    change(document["results"])
    path.write_text(yaml.safe_dump(document))


def test_every_federal_race_is_modeled_results_only_or_none():
    loaded = config.load_config(ROOT / "config")
    covered = config.coverage(loaded, config.load_results(loaded, ROOT / "config"))
    federal = set(districts.senate_race_ids()) | set(districts.house_race_ids())
    assert covered.keys() == federal, f"unregistered: {sorted(federal - covered.keys())[:10]}"
    assert sum(kind == "modeled" for kind in covered.values()) == 70  # 76 minus Ohio's 6 dropped forecasts
    assert sum(covered[race] == "results" for race in covered if race.startswith("2026-OH-H")) == 15
    assert covered["2026-OH-SEN-SPECIAL"] == "modeled"


def test_validate_reports_results_only_counts(results_dir):
    result = cli(results_dir)
    assert result.returncode == 0, result.stderr
    assert "0 not registered" in result.stdout


def test_house_template_fills_in_each_district_and_skips_modeled_ones(results_dir):
    loaded = results(results_dir)
    nc = {k: c for k, c in loaded.contests.items() if c.source == "NC/sbe"}
    assert "2026-NC-H01" not in nc and "2026-NC-H11" not in nc  # modeled
    assert len(nc) == 14 - 2
    assert nc["2026-NC-H02"].contest == "US HOUSE OF REPRESENTATIVES DISTRICT 02"
    assert loaded.contests["2026-SC-H02"].contest == "U.S.  House of Representatives, District  2"
    assert loaded.sources["NC/sbe"].feed.url == config.load_config(results_dir).feeds["2026-NC-SEN"].url


@pytest.mark.parametrize("change, message", [
    (lambda d: d["sources"]["sbe"]["contests"][0].update(districts=[1]), "modeled"),
    (lambda d: d["sources"]["sbe"]["contests"][0].update(districts=[15]), "no district"),
    (lambda d: d["sources"]["sbe"]["contests"][0].update(template="US HOUSE"), "template"),
    (lambda d: d["sources"]["sbe"]["contests"][0].update(template="DISTRICT {d}"), "template"),
    (lambda d: d["sources"]["sbe"]["contests"].append({"office": "senate"}), "modeled"),
    (lambda d: d["sources"]["sbe"].update(url="https://example.org/x"), "inherits"),
    (lambda d: d["sources"]["sbe"].update(same_as="2026-GA-SEN"), "same_as"),
    (lambda d: (d["sources"]["sbe"].update(status="ready"),
                d["sources"]["sbe"]["contests"][0].update(template=None)), "ready"),
    (lambda d: d.update(none={"senate": "no feed"}), "already has a source"),
    (lambda d: d.update(none={"2026-NC-H02": "no feed"}), "already has a source"),
])
def test_invalid_results_entries_fail(results_dir, change, message):
    edit_results(results_dir, "NC", change)
    with pytest.raises(config.ConfigError, match=message):
        results(results_dir)


def test_ready_results_source_needs_no_d_or_r(results_dir):
    edit_results(results_dir, "PA", lambda d: d.update(none={}, sources={"dos": {
        "adapter": "pa_dos", "url": "https://www.electionreturns.pa.gov/api", "election_id": None,
        "polls_close": "2026-11-03T20:00:00-05:00", "status": "ready",
        "contests": [{"office": "house", "districts": "all", "template": "Representative in Congress {n}"}],
    }}))
    loaded = results(results_dir)
    assert len([c for c in loaded.contests.values() if c.source == "PA/dos"]) == 17 - 4  # 4 modeled


def test_ready_results_source_needs_a_template_and_polls_close(results_dir):
    edit_results(results_dir, "PA", lambda d: d.update(none={}, sources={"dos": {
        "adapter": "pa_dos", "url": "https://www.electionreturns.pa.gov/api", "election_id": None,
        "status": "ready", "contests": [{"office": "house", "districts": "all", "template": None}],
    }}))
    with pytest.raises(config.ConfigError, match="ready"):
        results(results_dir)


@pytest.mark.parametrize("sides, ok", [
    ({"Jane Doe": "D", "John Roe": "R"}, True),
    ({"Jane Doe": "D", "Jim Doe": "D2"}, True),  # same-party top-two
    ({"Ann Lee": "I", "Ann Other": "other"}, True),
    ({"Jane Doe": "Democrat"}, False),
    ({"Jane Doe": "d"}, False),
    ({"A": "D", "B": "R", "C": "I", "E": "D2", "F": "R2", "G": "L"}, False),  # more than 5 named
])
def test_side_keys(results_dir, sides, ok):
    edit_results(results_dir, "NC", lambda d: d["sources"]["sbe"]["contests"][0].update(sides=sides))
    if ok:
        assert results(results_dir).contests["2026-NC-H02"].sides == sides
    else:
        with pytest.raises(config.ConfigError, match="sides"):
            results(results_dir)


def test_results_file_names_must_be_states(results_dir):
    (results_dir / "results" / "DC.yaml").write_text("results:\n  sources: {}\n")
    with pytest.raises(config.ConfigError, match="state code"):
        results(results_dir)


def test_a_broken_results_file_leaves_the_modeled_config_loadable(results_dir):
    (results_dir / "results" / "PA.yaml").write_text("results: [")
    config.load_config(results_dir)
    with pytest.raises(config.ConfigError, match="PA.yaml"):
        results(results_dir)


def test_house_file_adds_elections_and_refuses_duplicates(tmp_path, monkeypatch):
    (tmp_path / "house").mkdir()
    (tmp_path / "elections.yaml").write_text("NC:\n  2024_pres: {adapter: nc_sbe}\n")
    monkeypatch.setattr(elections, "CONFIG", tmp_path)
    (tmp_path / "house" / "NC.yaml").write_text("elections:\n  2024_house_02: {adapter: nc_sbe}\n")
    assert set(elections.specs("NC")) == {"2024_pres", "2024_house_02"}
    assert elections.load("NC", "2024_house_02").adapter == "nc_sbe"
    (tmp_path / "house" / "NC.yaml").write_text("elections:\n  2024_pres: {adapter: nc_sbe}\n")
    with pytest.raises(ValueError, match="both"):
        elections.specs("NC")


def test_a_live_forecast_cant_also_be_results_only_but_a_dropped_one_can(results_dir):
    def set_status(status):
        path = results_dir / "races.yaml"
        doc = yaml.safe_load(path.read_text())
        doc["races"]["2026-NC-H01"]["status"] = status
        path.write_text(yaml.safe_dump(doc))
    edit = results_dir / "results" / "NC.yaml"
    doc = yaml.safe_load(edit.read_text())
    doc["results"]["sources"]["sbe"]["contests"][0]["districts"] = [1, 2]
    edit.write_text(yaml.safe_dump(doc))
    with pytest.raises(config.ConfigError, match="modeled"):
        results(results_dir)
    set_status("dropped")
    loaded = config.load_config(results_dir)
    found = config.load_results(loaded, results_dir)
    assert "2026-NC-H01" in found.contests
    assert config.coverage(loaded, found)["2026-NC-H01"] == "results"
