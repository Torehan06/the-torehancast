"""feedcheck: config-driven URLs and the `--contests ST` report (no network)."""

from pathlib import Path

from torehancast import feedcheck
from torehancast.adapters import nc_sbe

FIXTURES = Path(__file__).parents[1] / "fixtures"


class FromFixture:
    """The NC adapter, with the download replaced by the 2024 House fixture."""

    parse_all_contests = staticmethod(nc_sbe.parse_all_contests)

    def __init__(self):
        self.fetched = []

    def fetch_source(self, client, feed):
        self.fetched.append(feed.url)
        return (FIXTURES / "nc/house_pct_20241105.txt").read_text()


def test_contests_report_shows_expected_found_and_missing_districts():
    fake = FromFixture()
    lines = feedcheck.contests_report("NC", client=object(), adapter=lambda name: fake)
    assert len(fake.fetched) == 1  # one download serves every contest of the source
    assert lines[0].startswith("NC/sbe  status=")
    # NC-1 and NC-11 are modeled, so the source serves the other 12 districts.
    assert lines[1].startswith("  expected 12, found 1; missing 2026-NC-H03, ")
    assert "2026-NC-H02" not in lines[1]
    assert lines[2] == ("  2026-NC-H02  ? reporting  D Deborah K. Ross 268,662; "
                        "R Alan D. Swain 128,164; G Michael Dublin 8,691")


def test_contests_report_survives_a_failing_source():
    class Broken(FromFixture):
        def fetch_source(self, client, feed):
            raise OSError("connection refused")

    lines = feedcheck.contests_report("NC", client=object(), adapter=lambda name: Broken())
    assert lines[1] == "  could not read: OSError: connection refused"


def test_contests_report_for_a_state_without_results_sources():
    assert feedcheck.contests_report("AK", client=object()) == [
        "AK: no results-only sources in config/results/AK.yaml"]


def test_config_urls_add_only_what_the_fixed_list_lacks():
    urls = feedcheck.config_urls()
    known = {u for us in feedcheck.CHECKS.values() for u in us}
    assert urls and not known & {u for us in urls.values() for u in us}
    assert "https://electionresultsfiles.sos.mn.gov/20261103/ussenatecty.txt" in urls["MN"]
